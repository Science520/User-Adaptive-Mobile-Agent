"""Bounded, resumable public-data sampling, including range reads of large ZIPs."""
import io
import binascii
import struct
import threading
import zlib
import json
import random
import re
import time
import urllib.parse
import urllib.request
import zipfile
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

from .io import sha256, write_json

HF = "https://huggingface.co/datasets/"
MPII_META = "https://darus.uni-stuttgart.de/api/datasets/:persistentId/?persistentId=doi:10.18419/darus-3240"


def request(url, headers=None):
    for attempt in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=60)
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))


def fetch(url, path, max_bytes=64 * 1024**2):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        with request(url) as response, temporary.open("wb") as output:
            total = 0
            while True:
                block = response.read(min(1024**2, max_bytes - total + 1))
                if not block:
                    break
                total += len(block)
                if total > max_bytes:
                    raise ValueError(f"Download exceeds {max_bytes} byte limit: {url}")
                output.write(block)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


class RemoteZipFile(io.RawIOBase):
    """Seekable HTTP range reader. Refuse 200 responses instead of downloading GBs."""

    def __init__(self, url, size, max_bytes=192 * 1024**2, block_size=128 * 1024):
        self.url, self.size, self.limit, self.block_size = url, size, max_bytes, block_size
        self.position, self.transferred = 0, 0
        self.cache = OrderedDict()

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset + (0 if whence == 0 else self.position if whence == 1 else self.size)
        if position < 0:
            raise ValueError("Negative seek")
        self.position = position
        return position

    def read(self, size=-1):
        end = self.size if size < 0 else min(self.position + size, self.size)
        output = bytearray()
        while self.position < end:
            start = self.position // self.block_size * self.block_size
            stop = min(start + self.block_size, self.size) - 1
            if start not in self.cache:
                count = stop - start + 1
                if self.transferred + count > self.limit:
                    raise ValueError("HTTP range sampling budget exceeded; reduce sample size")
                # Unique query prevents intermediary caches returning a different range.
                separator = "&" if "?" in self.url else "?"
                url = self.url + separator + "sample_offset=" + str(start)
                with request(url, {"Range": f"bytes={start}-{stop}"}) as response:
                    expected = f"bytes {start}-{stop}/{self.size}"
                    if response.status != 206 or response.headers.get("Content-Range") != expected:
                        raise ValueError("Server does not honor the requested byte range")
                    data = response.read(count + 1)
                    if len(data) != count:
                        raise ValueError("Incomplete range response")
                self.transferred += count
                self.cache[start] = data
                if len(self.cache) > 32:
                    self.cache.popitem(last=False)
            data = self.cache[start]
            self.cache.move_to_end(start)
            take = min(end - self.position, len(data) - (self.position - start))
            output.extend(data[self.position - start:self.position - start + take])
            self.position += take
        return bytes(output)


def safe_member_path(root, name):
    member = PurePosixPath(name)
    if member.is_absolute() or ".." in member.parts or "\\" in name:
        raise ValueError(f"Unsafe archive member: {name}")
    root = Path(root).resolve()
    target = (root / name).resolve()
    if root not in target.parents:
        raise ValueError(f"Archive member escapes destination: {name}")
    return target


def extract_selected(archive, names, root, max_uncompressed=256 * 1024**2):
    infos = [archive.getinfo(name) for name in sorted(set(names))]
    if sum(info.file_size for info in infos) > max_uncompressed:
        raise ValueError("Uncompressed sample exceeds extraction budget")
    records = []
    for info in infos:
        if info.is_dir():
            continue
        target = safe_member_path(root, info.filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_suffix(target.suffix + ".part")
            with archive.open(info) as source, temporary.open("wb") as output:
                while True:
                    data = source.read(1024**2)
                    if not data:
                        break
                    output.write(data)
            temporary.replace(target)
        records.append({"member": info.filename, "bytes": target.stat().st_size, "sha256": sha256(target)})
    return records


def extract_remote_selected(remote, archive, names, root, workers=6):
    """Read selected local ZIP entries concurrently using verified archive metadata.

    A 64KiB allowance covers local-header extra fields; CRC and uncompressed size
    are checked against the central directory. Budget is reserved before network IO.
    """
    infos = [archive.getinfo(name) for name in sorted(set(names)) if not archive.getinfo(name).is_dir()]
    if sum(info.file_size for info in infos) > 256 * 1024**2:
        raise ValueError("Uncompressed sample exceeds extraction budget")
    lock = threading.Lock()

    def extract(info):
        target = safe_member_path(root, info.filename)
        if target.exists():
            content = target.read_bytes()
            if len(content) == info.file_size and binascii.crc32(content) & 0xffffffff == info.CRC:
                return {"member": info.filename, "bytes": len(content), "sha256": sha256(target)}
        start = info.header_offset
        stop = min(remote.size - 1, start + 30 + len(info.filename.encode("utf-8")) + 65535 + info.compress_size - 1)
        count = stop - start + 1
        with lock:
            if remote.transferred + count > remote.limit:
                raise ValueError("HTTP range sampling budget exceeded")
            remote.transferred += count
        separator = "&" if "?" in remote.url else "?"
        with request(remote.url + separator + "sample_offset=" + str(start), {"Range": f"bytes={start}-{stop}"}) as response:
            if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{stop}/{remote.size}":
                raise ValueError("Server does not honor requested byte range")
            raw = response.read(count + 1)
        if len(raw) != count:
            raise ValueError("Incomplete ZIP entry range")
        header = struct.unpack("<IHHHHHIIIHH", raw[:30])
        signature, _, flags, method = header[:4]
        if signature != 0x04034b50 or flags & 1 or method != info.compress_type:
            raise ValueError("Unsupported or inconsistent ZIP local header")
        offset = 30 + header[-2] + header[-1]
        payload = raw[offset:offset + info.compress_size]
        if method == zipfile.ZIP_STORED:
            content = payload
        elif method == zipfile.ZIP_DEFLATED:
            decoder = zlib.decompressobj(-15)
            content = decoder.decompress(payload, info.file_size + 1)
            if not decoder.eof:
                raise ValueError("Invalid or oversized deflate entry")
        else:
            raise ValueError("Remote sampler supports stored/deflated ZIP entries only")
        if len(content) != info.file_size or binascii.crc32(content) & 0xffffffff != info.CRC:
            raise ValueError("ZIP entry size/CRC mismatch")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".part")
        temporary.write_bytes(content)
        temporary.replace(target)
        return {"member": info.filename, "bytes": len(content), "sha256": sha256(target)}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(extract, infos))


def hf_tree(repo, path=""):
    url = HF.replace("/datasets/", "/api/datasets/") + repo + "/tree/main/" + path
    with request(url + "?recursive=true&limit=1000") as response:
        return json.load(response)


def download_funui(root, screens=40, seed=42):
    root = Path(root)
    target = root / "raw/funui"
    repo = "Earthiii/FunUI-Benchmark"
    metadata = hf_tree(repo)
    base = HF + repo + "/resolve/main/"
    files = {item["path"]: item for item in metadata if item["type"] == "file"}
    for name in ["README.md"] + sorted(x for x in files if x.startswith("tasks_cn/")):
        fetch(base + name, target / name)
    annotations = json.loads((target / "tasks_cn/ui_grounding_cn.json").read_text())
    images = sorted({x["image"] for x in annotations})
    # Round robin across apps; then random order within apps. No difficulty-label selection.
    apps = {}
    rng = random.Random(seed)
    for image in images:
        apps.setdefault(re.sub(r"_\d+\.[^.]+$", "", image), []).append(image)
    for values in apps.values():
        rng.shuffle(values)
    selected = []
    while len(selected) < min(screens, len(images)):
        for app in sorted(apps):
            if apps[app] and len(selected) < screens:
                selected.append(apps[app].pop())
    remote = RemoteZipFile(base + "images_cn.zip", files["images_cn.zip"]["size"])
    with zipfile.ZipFile(remote) as archive:
        index = {PurePosixPath(name).name: name for name in archive.namelist() if not name.startswith("__MACOSX/")}
        missing = set(selected) - set(index)
        if missing:
            raise ValueError(f"Images absent from official ZIP: {sorted(missing)}")
        records = extract_remote_selected(remote, archive, [index[name] for name in selected], target)
    manifest = {"dataset": repo, "source": base, "seed": seed, "license": "CC-BY-SA-4.0",
                "sampling": "app-round-robin screens; all Chinese raw task annotations", "range_bytes": remote.transferred,
                "archive_metadata": files["images_cn.zip"], "selected_images": selected, "files": records}
    manifest["annotation_files"] = [{"file": str(p.relative_to(target)), "sha256": sha256(p)}
                                     for p in sorted((target / "tasks_cn").glob("*.json"))]
    write_json(target / "manifest.json", manifest)
    return manifest


def download_mpii(root, per_subject=24, seed=42):
    target = Path(root) / "raw/mpiifacegaze"
    with request(MPII_META) as response:
        metadata = json.load(response)
    write_json(target / "metadata.json", metadata)
    files = {x["dataFile"]["filename"]: x["dataFile"] for x in metadata["data"]["latestVersion"]["files"]}
    base = "https://darus.uni-stuttgart.de/api/access/datafile/"
    fetch(base + str(files["readme.txt"]["id"]), target / "readme.txt")
    file = files["Data.zip"]
    # MPII has tens of thousands of members: reading its central directory in tiny
    # ranges costs hundreds of TLS round trips on high-latency connections.
    remote = RemoteZipFile(base + str(file["id"]), file["filesize"], block_size=4 * 1024**2)
    rng = random.Random(seed)
    with zipfile.ZipFile(remote) as archive:
        names = archive.namelist()
        txts = [n for n in names if re.search(r"/p\d\d/p\d\d\.txt$", n)]
        if len(txts) != 15:
            raise ValueError(f"Expected 15 subject annotation files, found {len(txts)}")
        selected = txts + [n for n in names if "/Calibration/" in n and n.endswith(".mat")]
        extract_remote_selected(remote, archive, selected, target)
        selected_images = []
        available = set(names)
        for name in sorted(txts):
            lines = [line for line in (target / name).read_text().splitlines() if line.strip()]
            sampled = rng.sample(lines, min(per_subject, len(lines)))
            parent = str(PurePosixPath(name).parent)
            for line in sampled:
                image = parent + "/" + line.split()[0]
                if image not in available:
                    raise ValueError(f"Annotated MPII image missing: {image}")
                selected_images.append(image)
        records = extract_remote_selected(remote, archive, selected + selected_images, target)
    manifest = {"dataset": "MPIIFaceGaze", "source": MPII_META, "seed": seed,
                "license": "CC-BY-NC-SA-4.0", "sampling": "seeded random images per participant; not a temporal stream",
                "per_subject": per_subject, "selected_images": selected_images,
                "range_bytes": remote.transferred, "files": records}
    write_json(target / "manifest.json", manifest)
    return manifest


def download_mobileviews(root):
    target = Path(root) / "raw/mobileviews"
    repo = "mllmTeam/MobileViews"
    name = "MobileViews_Apps_CompleteTraces/OneExample.zip"
    url = HF + repo + "/resolve/main/" + name
    path = fetch(url, target / "OneExample.zip", max_bytes=64 * 1024**2)
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if not n.startswith("__MACOSX/") and (
                 (("/states/" in n or "/events/" in n) and n.lower().endswith((".json", ".png", ".jpg", ".jpeg")))
                 or n.endswith(("/actions.csv", "/utg.js")))]
        records = extract_selected(archive, names, target)
    manifest = {"dataset": repo, "source": url, "license": "MIT (dataset card)",
                "sampling": "official single-app example; cannot establish cross-app generalization",
                "archive_sha256": sha256(path), "files": records}
    write_json(target / "manifest.json", manifest)
    return manifest
