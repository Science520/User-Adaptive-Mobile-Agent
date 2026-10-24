import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .adapters import prepare
from .download import download_funui, download_mobileviews, download_mpii
from .evaluation import evaluate_synthetic, grounding, h1, make_report
from .io import write_json, sha256
from .pilot import evaluate_pilot, validate_pilot
from .synthetic import synthesize

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "configs/synthetic.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description="User-camera public-data validation (no GUI agent deployment)")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    download = sub.add_parser("download", help="Sample official public datasets with bounded downloads")
    download.add_argument("dataset", choices=["funui", "mpii", "mobileviews", "all"])
    download.add_argument("--data", default="data")
    download.add_argument("--screens", type=int, default=48)
    download.add_argument("--per-subject", type=int, default=24)
    download.add_argument("--seed", type=int, default=42)
    p = sub.add_parser("prepare", help="Parse official formats and write data audit")
    p.add_argument("--data", default="data")
    p = sub.add_parser("synthesize", help="Controlled UI redraws and explicit synthetic camera geometry")
    p.add_argument("--data", default="data")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--font")
    p.add_argument("--no-render", action="store_true")
    for name in ("h1", "evaluate", "report", "run"):
        p = sub.add_parser(name, help={"h1": "Measure image-only gaze/head/distance proxy baseline",
                                      "evaluate": "Evaluate synthetic H2/H3 ablations",
                                      "report": "Generate Chinese results report", "run": "Run all offline stages after download"}[name])
        p.add_argument("--data", default="data")
        p.add_argument("--output", default="reports")
        if name == "run":
            p.add_argument("--config", default=str(DEFAULT_CONFIG))
            p.add_argument("--font")
    p = sub.add_parser("grounding", help="Score FunUI external point predictions or center sanity baseline")
    p.add_argument("--data", default="data")
    p.add_argument("--output", default="reports")
    p.add_argument("--predictions", help="JSONL rows with id and point_px")
    p = sub.add_parser("pilot", help="Validate/score future synchronized feature windows")
    p.add_argument("path")
    p.add_argument("--validate-only", action="store_true")
    p.add_argument("--group-by", choices=["subject_id", "app_id"], default="subject_id")
    p.add_argument("--output", default="reports")
    args = parser.parse_args(argv)
    try:
        if args.command == "download":
            if args.screens <= 0 or args.per_subject <= 0:
                parser.error("Sample counts must be positive")
            result = {}
            for name, fn in [("funui", lambda: download_funui(args.data, args.screens, args.seed)),
                             ("mpii", lambda: download_mpii(args.data, args.per_subject, args.seed)),
                             ("mobileviews", lambda: download_mobileviews(args.data))]:
                if args.dataset in (name, "all"):
                    print(f"Downloading sample: {name}", flush=True)
                    manifest = fn()
                    result[name] = {"files": len(manifest["files"]), "range_bytes": manifest.get("range_bytes")}
        elif args.command == "prepare":
            result = prepare(args.data)
        elif args.command == "synthesize":
            result = synthesize(args.data, args.config, args.font, render=not args.no_render)
        elif args.command == "h1":
            result = h1(args.data, args.output)
        elif args.command == "evaluate":
            result = evaluate_synthetic(args.data, args.output)
        elif args.command == "grounding":
            result = grounding(args.data, args.output, args.predictions)
        elif args.command == "report":
            result = make_report(args.data, args.output)
        elif args.command == "pilot":
            if args.validate_only:
                from .io import read_jsonl
                result = validate_pilot(read_jsonl(args.path))
            else:
                result = evaluate_pilot(args.path, args.output, args.group_by)
        elif args.command == "run":
            audit = prepare(args.data)
            print("Data audit complete", flush=True)
            if "mpiifacegaze" in audit:
                h1(args.data, args.output)
                print("H1 baseline complete", flush=True)
            if "funui" in audit:
                grounding(args.data, args.output)
            synthesize(args.data, args.config, args.font)
            print("Synthetic generation complete", flush=True)
            evaluate_synthetic(args.data, args.output)
            result = make_report(args.data, args.output)
            import platform
            import PIL, numpy, scipy, sklearn
            write_json(Path(args.output) / "environment.json", {"python": platform.python_version(),
                       "platform": platform.platform(), "numpy": numpy.__version__, "scipy": scipy.__version__,
                       "sklearn": sklearn.__version__, "pillow": PIL.__version__, "package": __version__,
                       "config_sha256": sha256(args.config),
                       "code_sha256": {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))}})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
