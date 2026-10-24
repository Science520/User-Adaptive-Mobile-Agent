"""Strict adapters for raw official formats; invalid rows remain visible in audits."""
import json
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.io import loadmat

from .geometry import gaze_vector
from .io import write_json, write_jsonl


def bbox(value):
    if isinstance(value, str):
        value = json.loads(value)
    a = np.asarray(value, dtype=float).reshape(-1)
    if len(a) != 4 or not np.isfinite(a).all() or a[2] <= a[0] or a[3] <= a[1]:
        raise ValueError("Invalid xyxy bounding box")
    return a.tolist()


def in_screen(box, width, height):
    x1, y1, x2, y2 = box
    return 0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height


def prepare_funui(root):
    root = Path(root)
    folder = root / "raw/funui"
    manifest = json.loads((folder / "manifest.json").read_text())
    images = {p.name: p for p in folder.rglob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg")}
    selected = set(manifest["selected_images"])
    counters = Counter()
    elements, tasks, screens = defaultdict(list), [], []
    for task_file in sorted((folder / "tasks_cn").glob("*.json")):
        annotations = json.loads(task_file.read_text())
        counters[task_file.stem + "_all_rows"] = len(annotations)
        for index, row in enumerate(annotations):
            if row.get("image") not in selected:
                continue
            counters["sampled_task_rows"] += 1
            task = dict(row, id=f"{task_file.stem}:{index}", task=task_file.stem,
                        source="FunUI", image_path=str(images[row["image"]].resolve()))
            if task_file.stem.startswith("ui_grounding"):
                try:
                    box = bbox(row["bbox"])
                    with Image.open(images[row["image"]]) as im:
                        width, height = im.size
                    task["bbox_xyxy"] = box
                    task["bbox_valid"] = in_screen(box, width, height)
                    counters["grounding_out_of_screen_boxes"] += int(not task["bbox_valid"])
                    # Some official grounding items explicitly describe nonexistent elements.
                    try:
                        answer_box = bbox(row["answer"])
                        task["positive_grounding"] = answer_box == box
                    except (ValueError, TypeError, json.JSONDecodeError):
                        task["positive_grounding"] = False
                    task["question_contains_box"] = bool(re.search(r"\[\s*\d+\s*,\s*\d+\s*,", row["question"]))
                    counters["grounding_positive"] += int(task["positive_grounding"])
                    counters["grounding_negative_or_nonbox"] += int(not task["positive_grounding"])
                    counters["grounding_question_contains_box"] += int(task["question_contains_box"])
                    if task["positive_grounding"] and task["bbox_valid"]:
                        elements[row["image"]].append({"bounds": box, "text": "", "description": row["question"],
                                                        "clickable": None, "ui_type": row.get("ui_type")})
                except (ValueError, TypeError, KeyError):
                    counters["invalid_grounding_rows"] += 1
                    task["bbox_valid"] = False
            tasks.append(task)
    for name in sorted(selected):
        path = images[name]
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            width, height = im.size
        app = re.sub(r"_\d+\.[^.]+$", "", name)
        screens.append({"id": "funui:" + name, "source": "FunUI", "app_id": app,
                        "image_path": str(path.resolve()), "width": width, "height": height,
                        "annotation_coverage": "partial grounding boxes; not full hierarchy",
                        "elements": elements[name]})
    counters["screens"] = len(screens)
    counters["apps"] = len({s["app_id"] for s in screens})
    write_jsonl(root / "processed/funui_tasks.jsonl", tasks)
    return screens, dict(counters)


def prepare_mpii(root):
    root = Path(root)
    folder = root / "raw/mpiifacegaze"
    manifest = json.loads((folder / "manifest.json").read_text())
    wanted = set(manifest["selected_images"])
    rows, errors = [], []
    for annotation in sorted(folder.rglob("p[0-9][0-9].txt")):
        subject = annotation.stem
        cal = annotation.parent / "Calibration"
        sizes = list(cal.glob("*creenSize.mat"))
        if len(sizes) != 1:
            raise ValueError(f"Missing screen calibration for {subject}")
        screen = loadmat(sizes[0])
        width, height = [float(np.asarray(screen[k]).squeeze()) for k in ("width_pixel", "height_pixel")]
        camera = loadmat(cal / "Camera.mat")
        for line_no, line in enumerate(annotation.read_text().splitlines(), 1):
            if not line.strip():
                continue
            parts = line.split()
            relative = str(annotation.parent.relative_to(folder) / parts[0])
            if relative not in wanted:
                continue
            try:
                if len(parts) != 28:
                    raise ValueError(f"Expected 28 columns, got {len(parts)}")
                values = np.asarray(parts[1:27], dtype=float)
                if not np.isfinite(values).all():
                    raise ValueError("Nonfinite annotations")
                points = values[2:14].reshape(6, 2)
                rotation, translation = values[14:17], values[17:20]
                center, target = values[20:23], values[23:26]
                path = folder / relative
                with Image.open(path) as im:
                    im.verify()
                with Image.open(path) as im:
                    image_width, image_height = im.size
                rows.append({"id": relative, "subject_id": subject, "source": "MPIIFaceGaze",
                             "image_path": str(path.resolve()), "image_width": image_width, "image_height": image_height,
                             "gaze_screen_px": values[:2].tolist(), "screen_size_px": [width, height],
                             "landmarks_2d": points.tolist(), "head_rvec": rotation.tolist(),
                             "head_translation_mm": translation.tolist(), "face_center_mm": center.tolist(),
                             "gaze_target_mm": target.tolist(), "gaze_direction": gaze_vector(center, target).tolist(),
                             "face_camera_distance_proxy_mm": float(np.linalg.norm(center)),
                             "camera_matrix": camera["cameraMatrix"].tolist(), "eye_subset": parts[27],
                             "label_provenance": "gaze target annotation; estimated head pose/face center",
                             "temporal": False})
            except (ValueError, OSError) as exc:
                errors.append({"subject": subject, "line": line_no, "reason": str(exc)})
    write_jsonl(root / "processed/mpii.jsonl", rows)
    audit = {"rows": len(rows), "subjects": dict(Counter(r["subject_id"] for r in rows)), "invalid": errors,
             "missing_selected_images": sorted(wanted - {r["id"] for r in rows}),
             "distance_is_ground_truth": False, "real_temporal_stream": False}
    return audit


def mobile_bounds(value):
    if isinstance(value, str):
        found = re.findall(r"-?\d+", value)
        return bbox([float(x) for x in found])
    return bbox(value)


def flatten_views(obj):
    if isinstance(obj, dict):
        if "bounds" in obj:
            yield obj
        for key, value in obj.items():
            if key not in ("bounds",):
                yield from flatten_views(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from flatten_views(value)


def prepare_mobileviews(root):
    root = Path(root)
    folder = root / "raw/mobileviews"
    screens, invalid = [], []
    metadata_size_mismatches = 0
    for path in sorted(folder.rglob("state*.json")):
        try:
            obj = json.loads(path.read_text())
            # DroidBot stores the original absolute device/host path. Match the basename only.
            candidate = Path(obj.get("screenshot_path", "")).name
            matches = list(path.parent.glob(candidate)) if candidate else []
            if not matches:
                suffix = path.stem.removeprefix("state_")
                matches = [p for ext in ("png", "jpg", "jpeg") for p in path.parent.glob("screen_" + suffix + "." + ext)]
            if len(matches) != 1:
                raise ValueError("Missing or ambiguous screenshot")
            with Image.open(matches[0]) as im:
                im.verify()
            with Image.open(matches[0]) as im:
                width, height = im.size
            metadata_size_mismatches += int("width" in obj and (obj["width"], obj["height"]) != (width, height))
            elements = []
            for view in flatten_views(obj.get("views", [])):
                try:
                    box = mobile_bounds(view["bounds"])
                    # Full-screen layouts are containers, not interactive targets.
                    if not in_screen(box, width, height):
                        continue
                    elements.append({"bounds": box, "text": view.get("text") or view.get("content_description") or "",
                                     "clickable": bool(view.get("clickable", False)), "class": view.get("class", "")})
                except (ValueError, TypeError):
                    continue
            activity = obj.get("foreground_activity") or ""
            app = activity.split("/")[0] if "/" in activity else path.parent.parent.name
            screens.append({"id": "mobileviews:" + str(path.relative_to(folder)), "source": "MobileViews",
                            "app_id": app, "image_path": str(matches[0].resolve()), "width": width, "height": height,
                            "annotation_coverage": "view hierarchy", "elements": elements,
                            "foreground_activity": obj.get("foreground_activity"),
                            "collection_id": str(path.parent.parent.relative_to(folder)),
                            "state_str": obj.get("state_str"), "source_state": str(path.resolve())})
        except (ValueError, OSError, TypeError) as exc:
            invalid.append({"path": str(path), "reason": str(exc)})
    # A collected app trace can briefly enter system activities. It remains one group.
    owners = defaultdict(Counter)
    for screen in screens:
        owners[screen["collection_id"]][screen["app_id"]] += 1
    for screen in screens:
        screen["app_id"] = owners[screen["collection_id"]].most_common(1)[0][0]
    # Different state files can refer to identical screen content. Keep one to avoid leakage.
    unique = {}
    from .io import sha256
    for screen in screens:
        key = sha256(screen["image_path"])
        unique.setdefault(key, screen)
    screens = list(unique.values())
    transitions = []
    state_index = defaultdict(list)
    for screen in screens:
        state_index[screen.get("state_str")].append(screen["id"])
    action_stats = Counter()
    for action_path in sorted(folder.rglob("actions.csv")):
        collection = str(action_path.parent.relative_to(folder))
        previous_to, segment = None, 0
        with action_path.open(newline="") as stream:
            for index, action in enumerate(csv.DictReader(stream)):
                raw = action["action"]
                box_match = re.search(r"bound_box=(-?\d+,-?\d+,-?\d+,-?\d+)", raw)
                box = None
                if box_match:
                    try:
                        box = bbox([int(x) for x in box_match[1].split(",")])
                    except ValueError:
                        action_stats["invalid_action_boxes"] += 1
                if previous_to is not None and previous_to != action["from_state"]:
                    segment += 1
                    action_stats["csv_sequence_discontinuities"] += 1
                previous_to = action["to_state"]
                from_ids, to_ids = state_index[action["from_state"]], state_index[action["to_state"]]
                action_stats["unmapped_from_states"] += int(not from_ids)
                action_stats["unmapped_to_states"] += int(not to_ids)
                action_type = raw.split(" ", 1)[0]
                action_stats["type_" + action_type] += 1
                transitions.append({"id": f"mobileviews:{collection}:action:{index}", "collection_id": collection,
                                    "sequence_index": index, "contiguous_segment": segment,
                                    "from_state": action["from_state"], "to_state": action["to_state"],
                                    "from_screen_ids": from_ids, "to_screen_ids": to_ids,
                                    "action_type": action_type, "action_bbox_px": box, "raw_action": raw,
                                    "timestamp_ms": None, "camera_stream": None,
                                    "provenance": "official DroidBot explorer trace; not human actions/difficulty labels"})
    write_jsonl(root / "processed/mobileviews_actions.jsonl", transitions)
    return screens, {"screens": len(screens), "invalid": invalid,
                     "apps": len({s["app_id"] for s in screens}),
                     "state_metadata_size_mismatches": metadata_size_mismatches,
                     "action_rows": len(transitions), "action_audit": dict(action_stats),
                     "has_synchronized_user_camera": False}


def prepare(root):
    root = Path(root)
    all_screens, audit = [], {}
    for name, fn in [("funui", prepare_funui), ("mobileviews", prepare_mobileviews)]:
        if (root / "raw" / name / "manifest.json").exists():
            screens, report = fn(root)
            all_screens.extend(screens)
            audit[name] = report
    if (root / "raw/mpiifacegaze/manifest.json").exists():
        audit["mpiifacegaze"] = prepare_mpii(root)
    if not audit:
        raise ValueError("No downloaded datasets. Run download first.")
    write_jsonl(root / "processed/screens.jsonl", all_screens)
    # Hierarchy box height is a layout measurement, never substituted for glyph height.
    features = []
    for screen in all_screens:
        clickables = [e for e in screen["elements"] if e.get("clickable")]
        boxes = [e["bounds"] for e in clickables]
        text_boxes = [e["bounds"] for e in screen["elements"] if e.get("text")]
        features.append({"screen_id": screen["id"], "source": screen["source"], "app_id": screen["app_id"],
                         "annotated_element_count": len(screen["elements"]),
                         "clickable_count": len(clickables) if screen["source"] == "MobileViews" else None,
                         "clickable_density_per_megapixel": len(clickables) * 1e6 / (screen["width"] * screen["height"]) if screen["source"] == "MobileViews" else None,
                         "minimum_clickable_area_px2": min(((b[2]-b[0])*(b[3]-b[1]) for b in boxes), default=None),
                         "minimum_text_container_height_px": min((b[3]-b[1] for b in text_boxes), default=None),
                         "glyph_height_px": None, "annotation_coverage": screen["annotation_coverage"]})
    write_jsonl(root / "processed/screen_features.jsonl", features)
    write_json(root / "processed/audit.json", audit)
    return audit
