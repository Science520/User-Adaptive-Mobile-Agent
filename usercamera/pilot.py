"""Offline feature-table validation for a future synchronized pilot, without camera capture."""
from collections import Counter
from pathlib import Path
import math

from .evaluation import ablate, matrix
from .io import read_jsonl, sha256, write_json


def validate_pilot(rows, tolerance_ms=100):
    if not rows:
        raise ValueError("Pilot table is empty")
    seen = set()
    trajectories = {}
    for row in rows:
        if row.get("evidence_tier") != "real_synchronized":
            raise ValueError("Pilot evaluation requires real_synchronized rows")
        if row["id"] in seen:
            raise ValueError("Duplicate pilot window ID")
        seen.add(row["id"])
        for key in ("subject_id", "app_id", "trajectory_id", "camera_stream_id", "screen_stream_id"):
            if not row.get(key):
                raise ValueError("Missing pilot identity: " + key)
        owner = (row["subject_id"], row["app_id"])
        if trajectories.setdefault(row["trajectory_id"], owner) != owner:
            raise ValueError("Trajectory assigned to different participants/apps")
        if row.get("clock") != "common_monotonic_ms":
            raise ValueError("Timestamps must use a common monotonic clock")
        start, end = row["input_start_ms"], row["input_end_ms"]
        all_times = [start, end, row["label_time_ms"], row["camera_timestamp_ms"],
                     row["screen_timestamp_ms"], row["action_cutoff_ms"]]
        if any(not math.isfinite(t) or t < 0 for t in all_times):
            raise ValueError("All timestamps must be finite and nonnegative")
        if start > end or end > row["label_time_ms"]:
            raise ValueError("Input window extends beyond label/prediction time")
        times = [row["camera_timestamp_ms"], row["screen_timestamp_ms"], row["action_cutoff_ms"]]
        if any(t < start or t > end for t in times):
            raise ValueError("Stream timestamp outside causal input window")
        if abs(times[0] - times[1]) > tolerance_ms:
            raise ValueError("Camera/screen synchronization tolerance exceeded")
        if row.get("difficulty_label_source") not in ("self_report", "independent_annotator"):
            raise ValueError("Difficulty requires an independent human label, not a feature formula/outcome")
        if row.get("difficulty") not in ("none", "visual", "motor", "navigation", "semantic", "cognitive_overload"):
            raise ValueError("Unknown real difficulty category")
        if row.get("intervention_label_source") != "independent_annotator":
            raise ValueError("Intervention requires independent annotation")
        if row.get("intervention") not in ("none", "zoom", "hint"):
            raise ValueError("Supported intervention classes: none/zoom/hint")
        matrix([row], "SAU")
    return {"rows": len(rows), "subjects": dict(Counter(r["subject_id"] for r in rows)),
            "apps": dict(Counter(r["app_id"] for r in rows)), "synchronization_tolerance_ms": tolerance_ms,
            "note": "Metadata checks do not prove physical synchronization or annotation validity; audit raw streams."}


def evaluate_pilot(path, output, group_by="subject_id", seed=42):
    rows = read_jsonl(path)
    validation = validate_pilot(rows)
    if group_by not in ("subject_id", "app_id"):
        raise ValueError("Use participant-held-out or app-held-out evaluation")
    result = {"evidence_tier": "real_synchronized", "validation": validation, "group_by": group_by,
              "input_sha256": sha256(path), "seed": seed,
              "limitations": ["Held-out participant and held-out app are separate analyses; run both.",
                              "Independent labels are required; classification does not establish intervention benefit.",
                              "Pilot metadata is user-supplied; raw synchronization and consent are outside this scorer."]}
    for target in ("difficulty", "intervention"):
        result[target], _, _ = ablate(rows, target, group_key=group_by, seed=seed)
    write_json(Path(output) / ("pilot_" + group_by + ".json"), result)
    return result
