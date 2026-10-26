import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .adapters import prepare, prepare_mpii
from .download import download_funui, download_mobileviews, download_mpii
from .evaluation import evaluate_synthetic, grounding, h1, make_report
from .io import write_json, sha256
from .pilot import evaluate_pilot, validate_pilot
from .synthetic import synthesize

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "configs/synthetic.json"


def run_mpii_command(args):
    if args.command == "mpii-integrate-expansion":
        from .mpii_expansion import integrate_expansion
        return integrate_expansion(args.data,args.expansion,args.output)
    if args.command == "mpii-eval-expanded":
        from .mpii_expansion import evaluate_expanded
        return evaluate_expanded(args.data,args.output,args.run_neural,args.max_epochs)
    if args.command == "mpii-audit-outliers":
        from .mpii_outlier_audit import audit_outliers
        return audit_outliers(args.data, args.output)
    if args.command == "mpii-compare-cleaning":
        from .mpii_cleaning import compare_cleaning
        return compare_cleaning(args.data, args.output, args.splits, args.extra_per_subject,
                                args.allow_download, args.download_budget_mib, args.expansion_dir)
    if args.command == "mpii-strong-baselines":
        from .mpii_strong import strong_baselines
        return strong_baselines(args.data, args.output, args.splits, args.max_epochs, not args.no_neural)
    if args.command == "mpii-coarse-eval":
        from .mpii_coarse import coarse_eval
        from .mpii_next_report import generate_next_report
        result = coarse_eval(args.data, args.output, args.strong_output, args.splits)
        result['research_report'] = generate_next_report(args.audit_output, args.cleaning_output, args.strong_output, args.output)
        return result
    from .camera_screen_geometry import validate_geometry
    from .mpii_models import evaluate_models, prepare_weights, MAIN_MODEL
    from .mpii_report import generate_report
    if args.command == "mpii-prepare":
        return prepare_mpii(args.data)
    if args.command == "mpii-weights":
        return prepare_weights(args.data)
    if args.command == "mpii-geometry":
        r = validate_geometry(args.data, args.output)
        return {"report": str(Path(args.output)/"geometry_consistency.json"), "sample_n": r["n"], "all_annotations": r["all_local_annotations"]}
    if args.command == "mpii-models":
        r = evaluate_models(args.data, args.output, not args.no_cnn)
        return {"report": str(Path(args.output)/"h1_models.json"), "n": r["n"], "models": list(r["models"])}
    if args.command == "mpii-visualize":
        from .visualize_mpii import visualize
        return visualize(args.data, args.output, args.count)
    if args.command == "mpii-report":
        path = generate_report(args.data, args.output)
        if Path(args.output).resolve() == Path("reports/mpii_geometry").resolve():
            Path("reports/RESULTS.md").write_bytes(Path(path).read_bytes())
        return path
    if args.command == "mpii-run":
        import platform
        import shlex
        from datetime import datetime, timezone, timedelta
        import numpy, scipy, sklearn, PIL
        from .visualize_mpii import visualize
        output, data = Path(args.output), Path(args.data)
        legacy = [output.parent / name for name in ("h2_h3_synthetic.json", "synthetic_predictions.jsonl")]
        before = {str(p): sha256(p) for p in legacy if p.exists()}
        audit = prepare_mpii(data)
        print("MPII local parsing complete", flush=True)
        geo = validate_geometry(data, output)
        print("Geometry consistency complete (not prediction accuracy)", flush=True)
        models = evaluate_models(data, output, not args.no_cnn)
        figures = visualize(data, output, args.count, MAIN_MODEL if not args.no_cnn else "landmarks_head_pose_ridge")
        after = {str(p): sha256(p) for p in legacy if p.exists()}
        if before != after:
            raise ValueError("Legacy H2/H3 files unexpectedly changed")
        manifest = {"completed_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
                    "command": shlex.join([sys.executable, "-m", "usercamera"] + sys.argv[1:]),
                    "dataset_downloads": 0, "raw_manifest_sha256": sha256(data/"raw/mpiifacegaze/manifest.json"),
                    "input_sha256": sha256(data/"processed/mpii.jsonl"), "python": platform.python_version(),
                    "numpy": numpy.__version__, "scipy": scipy.__version__, "sklearn": sklearn.__version__, "pillow": PIL.__version__,
                    "cnn_runtime": {k: models["backbone"]["fingerprint"][k] for k in ("torch", "torchvision")} if models["backbone"] else None,
                    "checkpoint_sha256": models["backbone"]["fingerprint"]["weights_sha256"] if models["backbone"] else None,
                    "original_raw_files_sha256_verified": audit["original_manifest_files_sha256_verified"],
                    "successful_models": list(models["models"]), "sample_n": audit["rows"],
                    "geometry_all_labels": geo["all_local_annotations"]["n"], "visualizations": figures,
                    "legacy_H2_H3_sha256_unchanged": before,
                    "code_sha256": {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))}}
        write_json(output/"run_manifest.json", manifest)
        path = generate_report(data, output)
        if output.resolve() == Path("reports/mpii_geometry").resolve():
            Path("reports/RESULTS.md").write_bytes(Path(path).read_bytes())
        return {"report": path, "data_downloads": 0, "successful_models": list(models["models"]), "visualizations": figures}


def run_temporal_command(args):
    if args.command == "pilot-build-stimuli":
        from .pilot_stimuli import build_stimuli,export_recorded_ui
        if args.session:return export_recorded_ui(args.session,args.output,args.allow_mock)
        return build_stimuli(args.output,args.seed,args.repetitions,args.previews,args.mock_output)
    if args.command == "pilot-verify-session":
        from .pilot_session import verify_session
        return verify_session(args.path,args.output,args.allow_mock,args.allow_estimated_clock)
    if args.command == "pilot-extract-features":
        from .pilot_features import extract_features
        path=Path(args.path)
        paths=[path] if path.is_file() or (path/'session.json').exists() else sorted(p.parent for p in path.rglob('session.json'))
        if not paths:raise ValueError('No sessions found')
        return [extract_features(p,args.output,args.backend,args.model,args.detector_model,args.allow_mock,args.allow_estimated_clock) for p in paths]
    if args.command == "pilot-evaluate":
        from .pilot_temporal import evaluate_temporal
        return evaluate_temporal(args.features,args.output,args.allow_mock,tuple(args.algorithms.split(',')))
    if args.command == "pilot-report":
        from .pilot_report import generate_pilot_report
        return generate_pilot_report(args.output,args.expansion_output)


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
    for name in ("mpii-prepare", "mpii-weights", "mpii-geometry", "mpii-models", "mpii-visualize", "mpii-report", "mpii-run"):
        p = sub.add_parser(name, help="MPIIFaceGaze camera-screen geometry / participant-disjoint gaze validation")
        p.add_argument("--data", default="data")
        p.add_argument("--output", default="reports/mpii_geometry")
        if name in ("mpii-models", "mpii-run"):
            p.add_argument("--no-cnn", action="store_true")
        if name in ("mpii-visualize", "mpii-run"):
            p.add_argument("--count", type=int, default=30)
    for name, directory in [("mpii-audit-outliers", "reports/mpii_audit"),
                            ("mpii-compare-cleaning", "reports/mpii_next/cleaning"),
                            ("mpii-strong-baselines", "reports/mpii_next/strong"),
                            ("mpii-coarse-eval", "reports/mpii_next/coarse")]:
        p = sub.add_parser(name, help="Immutable MPII audit / shared LOSO research evaluation")
        p.add_argument("--data", default="data")
        p.add_argument("--output", default=directory)
        if name != "mpii-audit-outliers":
            p.add_argument("--splits", default="reports/mpii_next/splits.json")
        if name == "mpii-compare-cleaning":
            p.add_argument("--extra-per-subject", type=int, default=24)
            p.add_argument("--allow-download", action="store_true")
            p.add_argument("--download-budget-mib", type=float, default=64)
            p.add_argument("--expansion-dir", default="data/expansions/mpii_v1")
        if name == "mpii-strong-baselines":
            p.add_argument("--max-epochs", type=int, default=12)
            p.add_argument("--no-neural", action="store_true")
        if name == "mpii-coarse-eval":
            p.add_argument("--strong-output", default="reports/mpii_next/strong")
            p.add_argument("--audit-output", default="reports/mpii_audit")
            p.add_argument("--cleaning-output", default="reports/mpii_next/cleaning")
    for name in ("mpii-integrate-expansion","mpii-eval-expanded"):
        p=sub.add_parser(name,help="Isolated MPII720 view and fixed-original-test scale comparison")
        p.add_argument('--data',default='data');p.add_argument('--output',default='reports/mpii_expansion')
        if name=='mpii-integrate-expansion':p.add_argument('--expansion',default='data/expansions/mpii_v1')
        else:
            p.add_argument('--run-neural',action='store_true',help='Run estimated CPU workload explicitly; default lightweight Ridge only')
            p.add_argument('--max-epochs',type=int,default=12)
    for name in ('pilot-build-stimuli','pilot-verify-session','pilot-extract-features','pilot-evaluate','pilot-report'):
        p=sub.add_parser(name,help='Temporal mobile pilot; mock evidence is never real H2/H3')
        p.add_argument('--output',default='mobile_pilot/stimuli' if name=='pilot-build-stimuli' else 'reports/pilot')
        if name=='pilot-build-stimuli':
            p.add_argument('--seed',type=int,default=42);p.add_argument('--repetitions',type=int,default=2)
            p.add_argument('--previews',type=int,default=6);p.add_argument('--mock-output')
            p.add_argument('--session',help='Export exact recorded app PNG+measured metadata instead of generating new tasks')
            p.add_argument('--allow-mock',action='store_true')
        if name in ('pilot-verify-session','pilot-extract-features'):
            p.add_argument('path');p.add_argument('--allow-mock',action='store_true');p.add_argument('--allow-estimated-clock',action='store_true')
        if name=='pilot-extract-features':
            p.add_argument('--backend',choices=['mediapipe','mock'],default='mediapipe')
            p.add_argument('--model',default='data/models/face_landmarker.task')
            p.add_argument('--detector-model',default=None,help='Optional separate FaceDetector .tflite for actual confidence scores')
        if name=='pilot-evaluate':
            p.add_argument('--features',default='reports/pilot/features');p.add_argument('--allow-mock',action='store_true')
            p.add_argument('--algorithms',default='logistic,hist_gradient_boosting,gru')
        if name=='pilot-report':p.add_argument('--expansion-output',default='reports/mpii_expansion')
    p = sub.add_parser("pilot", help="Validate/score future synchronized feature windows")
    p.add_argument("path")
    p.add_argument("--validate-only", action="store_true")
    p.add_argument("--group-by", choices=["subject_id", "app_id"], default="subject_id")
    p.add_argument("--output", default="reports")
    args = parser.parse_args(argv)
    try:
        if args.command.startswith("pilot-"):
            result = run_temporal_command(args)
        elif args.command.startswith("mpii-"):
            result = run_mpii_command(args)
        elif args.command == "download":
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
