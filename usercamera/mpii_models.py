"""Participant-disjoint gaze probes with strictly separated inputs and targets.

ImageNet CNN is frozen; only small linear gaze/screen/origin heads are fit.
The six supplied landmarks assist cropping (oracle localization), and supplied
head pose is an estimated annotation, not a newly trained head-pose detector.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image
from sklearn.decomposition import PCA
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .camera_screen_geometry import describe, intersect_gaze, px_to_mm
from .evaluation import grouped_folds
from .geometry import angular_errors_deg
from .io import read_jsonl, sha256, write_json, write_jsonl

WEIGHTS_NAME = "resnet18-f37072fd.pth"
MAIN_MODEL = "appearance_head_pose_calibration_ridge"


def prepare_weights(root="data"):
    """Explicit opt-in download of NEW model weights, never dataset downloads."""
    import torch
    url = "https://download.pytorch.org/models/" + WEIGHTS_NAME
    path = Path(root) / "cache/torch/hub/checkpoints" / WEIGHTS_NAME
    reused = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not reused:
        torch.hub.download_url_to_file(url, str(path), hash_prefix="f37072fd", progress=False)
    if not sha256(path).startswith("f37072fd"):
        raise ValueError("Official ImageNet checkpoint hash mismatch")
    return {"path": str(path), "sha256": sha256(path), "url": url, "reused": reused, "dataset_downloads": 0}


def crop_boxes(row):
    """Image-left/right refer to image position, not anatomical eye identity."""
    points = np.asarray(row["landmarks_2d"], dtype=float).reshape(6, 2)
    width, height = row["image_width"], row["image_height"]
    if not np.isfinite(points).all() or (points < 0).any() or (points > [width, height]).any():
        raise ValueError("Invalid or out-of-image crop landmarks")
    span = np.ptp(points, axis=0)
    if (span < 2).any():
        raise ValueError("Degenerate facial landmarks")
    center = (points.max(axis=0) + points.min(axis=0)) / 2
    face = [center[0], center[1] - .1 * span[1], 2 * span[0], 3 * span[1]]
    rects = [face]
    pairs = sorted([points[:2], points[2:4]], key=lambda p: p[:, 0].mean())
    for eye in pairs:
        distance = np.linalg.norm(eye[1] - eye[0])
        if distance < 2:
            raise ValueError("Degenerate eye corners")
        rects.append([*eye.mean(axis=0), 2.4 * distance, 1.4 * distance])
    boxes = []
    for x, y, w, h in rects:
        b = [max(0, int(np.floor(x-w/2))), max(0, int(np.floor(y-h/2))),
             min(width, int(np.ceil(x+w/2))), min(height, int(np.ceil(y+h/2)))]
        if b[2] <= b[0] or b[3] <= b[1]:
            raise ValueError("Empty face/eye crop")
        boxes.append(b)
    return boxes


def metadata_features(row):
    """Whitelist of contemporaneous, non-target features. No label-derived gaze."""
    landmarks = (np.asarray(row["landmarks_2d"]) / [row["image_width"], row["image_height"]]).reshape(-1)
    pose = np.r_[row["head_rvec"], np.asarray(row["head_translation_mm"]) / 1000]
    c = row["calibration"]
    K, s = np.asarray(c["camera"]["K"]), c["screen"]
    calibration = np.r_[K[0, 0] / row["image_width"], K[1, 1] / row["image_height"],
                        K[0, 2] / row["image_width"], K[1, 2] / row["image_height"],
                        c["camera"]["distortion_coefficients"], np.asarray(s["R_screen_to_camera"]).reshape(-1),
                        np.asarray(s["t_screen_to_camera_mm"]) / 1000,
                        s["width_mm"] / 1000, s["height_mm"] / 1000,
                        s["width_pixel"] / 2000, s["height_pixel"] / 2000]
    return {"landmarks": landmarks, "head_pose": pose, "calibration": calibration}


def pixel_features(rows):
    values = []
    for row in rows:
        with Image.open(row["image_path"]) as image:
            values.append(np.asarray(image.convert("L").resize((32, 24)), dtype=float).reshape(-1) / 255)
    return np.asarray(values)


def cnn_features(rows, root, batch_size=12):
    import torch
    import torchvision
    from torchvision.models import resnet18, ResNet18_Weights
    root = Path(root)
    weights = root / "cache/torch/hub/checkpoints" / WEIGHTS_NAME
    if not weights.is_file():
        raise ValueError("ImageNet weights absent. Run explicit mpii-weights command once; model evaluation never downloads.")
    digest = sha256(weights)
    if not digest.startswith("f37072fd"):
        raise ValueError("Official ResNet18 checkpoint hash mismatch")
    cache = root / "cache/mpii_cnn_features.npz"
    manifest_path = cache.with_suffix(".json")
    fingerprint = {"schema": "face-eyes-resnet18-v1", "weights_sha256": digest,
                   "torch": torch.__version__, "torchvision": torchvision.__version__,
                   "preprocessing": "fixed landmark boxes; ImageNet resize256/center224/mean/std; no flips",
                   "samples": [{"id": r["id"], "image_sha256": sha256(r["image_path"]), "boxes": crop_boxes(r)} for r in rows]}
    if cache.exists() and manifest_path.exists():
        existing = json.loads(manifest_path.read_text())
        if existing.get("fingerprint") == fingerprint and existing.get("feature_sha256") == sha256(cache):
            with np.load(cache, allow_pickle=False) as f:
                values = f["features"]
            if values.shape == (len(rows), 1536) and np.isfinite(values).all():
                return values, existing
    torch.manual_seed(42)
    torch.set_num_threads(2)
    model = resnet18(weights=None)
    model.load_state_dict(torch.load(weights, map_location="cpu", weights_only=True))
    model.fc = torch.nn.Identity()
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    transform = ResNet18_Weights.IMAGENET1K_V1.transforms()
    values, crops, crop_manifest = [], [], []
    with torch.inference_mode():
        for index, row in enumerate(rows):
            boxes = crop_boxes(row)
            with Image.open(row["image_path"]) as image:
                image = image.convert("RGB")
                crops.extend(transform(image.crop(box)) for box in boxes)
            crop_manifest.append({"id": row["id"], "boxes_xyxy": boxes})
            if len(crops) >= batch_size * 3 or index == len(rows)-1:
                values.append(model(torch.stack(crops)).numpy())
                crops = []
                print(f"CNN features: {index+1}/{len(rows)} images", flush=True)
    features = np.concatenate(values).reshape(len(rows), 1536)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, features=features)
    manifest = {"fingerprint": fingerprint, "feature_sha256": sha256(cache), "device": "cpu",
                "crop_localization": "six supplied annotated landmarks; not image-only detector",
                "weights_pretraining": "ImageNet-1K, not MPIIFaceGaze", "frozen_backbone": True}
    write_json(manifest_path, manifest)
    write_jsonl(root / "processed/mpii_crops.jsonl", crop_manifest)
    return features, manifest


def build_feature_sets(rows, appearance=None):
    metadata = [metadata_features(row) for row in rows]
    blocks = {name: np.stack([m[name] for m in metadata]) for name in metadata[0]}
    result = {"pixels32x24_ridge": (pixel_features(rows), 0),
              "landmarks_only_ridge": (blocks["landmarks"], 0), "head_pose_only_ridge": (blocks["head_pose"], 0),
              "landmarks_head_pose_ridge": (np.c_[blocks["landmarks"], blocks["head_pose"]], 0),
              "calibration_only_ridge": (blocks["calibration"], 0)}
    if appearance is not None:
        result.update({"face_cnn_ridge": (appearance[:, :512], 512),
                       "face_eye_cnn_ridge": (appearance, 1536),
                       "appearance_head_pose_ridge": (np.c_[appearance, blocks["head_pose"]], 1536),
                       MAIN_MODEL: (np.c_[appearance, blocks["head_pose"], blocks["calibration"]], 1536)})
    for name, (x, _) in result.items():
        if not np.isfinite(x).all():
            raise ValueError(f"Nonfinite features: {name}")
    return result


def fit_predict_fold(x, target, train, test, appearance_dims=0):
    """Every learned transform is fitted on training participants only."""
    if appearance_dims:
        appearance = make_pipeline(StandardScaler(), PCA(n_components=min(32, len(train)-1), svd_solver="randomized", random_state=42))
        a = appearance.fit_transform(x[train, :appearance_dims])
        b = appearance.transform(x[test, :appearance_dims])
        if x.shape[1] > appearance_dims:
            metadata = StandardScaler()
            a = np.c_[a, metadata.fit_transform(x[train, appearance_dims:])]
            b = np.c_[b, metadata.transform(x[test, appearance_dims:])]
        model = Ridge(alpha=100, solver="lsqr").fit(a, target[train])
        return model.predict(b)
    model = make_pipeline(StandardScaler(), Ridge(alpha=100, solver="lsqr"))
    model.fit(x[train], target[train])
    return model.predict(x[test])


def prediction_errors(prediction, rows):
    # Primary 2D score uses the independently regressed screen head; no annotated gaze origin is needed.
    target_direction = np.asarray([r["gaze_direction"] for r in rows])
    angles = angular_errors_deg(prediction[:, :3], target_direction)
    angles[np.linalg.norm(prediction[:, :3], axis=1) < 1e-10] = 180  # explicit worst-angle penalty, never NaN->90
    per_sample = []
    for i, row in enumerate(rows):
        cal = row["calibration"]
        s = cal["screen"]
        pixel = prediction[i, 3:5] * [s["width_pixel"], s["height_pixel"]]
        pixel_delta = pixel - row["gaze_screen_px"]
        mm_delta = px_to_mm(pixel_delta, cal)
        item = {"angular_error_deg": float(angles[i]), "screen_direct_px": pixel.tolist(),
                "screen_direct_error_px": float(np.linalg.norm(pixel_delta)),
                "screen_direct_error_mm": float(np.linalg.norm(mm_delta)),
                "predicted_gaze_direction": (prediction[i, :3] / max(np.linalg.norm(prediction[i, :3]), 1e-12)).tolist(),
                "predicted_face_center_mm": (prediction[i, 5:8] * 1000).tolist(),
                "degenerate_predicted_direction": bool(np.linalg.norm(prediction[i, :3]) < 1e-10)}
        # Distinguish model-predicted origin from an explicitly conditional annotated-origin diagnostic.
        for name, origin in [("predicted_origin_ray", prediction[i, 5:8] * 1000),
                             ("annotated_origin_ray", row["face_center_mm"])]:
            try:
                ray = intersect_gaze(origin, prediction[i, :3], cal)
                delta = np.asarray(ray["screen_xy_px"]) - row["gaze_screen_px"]
                item[name] = {"valid": True, "screen_px": ray["screen_xy_px"], "error_px": float(np.linalg.norm(delta)),
                              "error_mm": float(np.linalg.norm(px_to_mm(delta, cal))),
                              "uses_annotated_origin": name == "annotated_origin_ray"}
            except ValueError as exc:
                item[name] = {"valid": False, "failure": str(exc)}
        per_sample.append(item)
    metrics = {key: describe([r[key] for r in per_sample]) for key in ("angular_error_deg", "screen_direct_error_px", "screen_direct_error_mm")}
    for name in ("predicted_origin_ray", "annotated_origin_ray"):
        valid = [r[name] for r in per_sample if r[name]["valid"]]
        metrics[name] = {"error_px_valid_only": describe([r["error_px"] for r in valid]),
                         "error_mm_valid_only": describe([r["error_mm"] for r in valid]),
                         "invalid_count": len(rows)-len(valid), "total": len(rows),
                         "coverage": len(valid)/len(rows)}
    return metrics, per_sample


def evaluate_models(root="data", output="reports/mpii_geometry", use_cnn=True):
    root, output = Path(root), Path(output)
    path = root / "processed/mpii.jsonl"
    rows = read_jsonl(path)
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate sample IDs")
    groups = np.asarray([r["subject_id"] for r in rows])
    folds = grouped_folds(groups)
    # Targets are built separately; there is no target-dependent normalization/crop.
    target = np.asarray([list(r["gaze_direction"]) + (np.asarray(r["gaze_screen_px"])/r["screen_size_px"]).tolist()
                         + (np.asarray(r["face_center_mm"])/1000).tolist() for r in rows])
    appearance, backbone = cnn_features(rows, root) if use_cnn else (None, None)
    feature_sets = build_feature_sets(rows, appearance)
    prediction_rows = [{"id": r["id"], "subject_id": r["subject_id"], "official_target_px": r["gaze_screen_px"], "models": {}} for r in rows]
    report = {"task": "participant-disjoint model prediction", "input_sha256": sha256(path), "n": len(rows),
              "backbone": backbone, "models": {}, "seed": 42,
              "protocol": "fixed 5-fold GroupKFold by participant; train-only scaling/PCA and Ridge alpha=100; no tuning on test",
              "skipped_models": [] if use_cnn else ["all CNN models (--no-cnn)"],
              "folds": [{"fold": i, "train_subjects": sorted(set(groups[a])), "test_subjects": sorted(set(groups[b]))} for i, (a,b) in enumerate(folds)],
              "primary_2d_metric": "direct normalized-screen head, evaluated without annotated gaze origin; pixel and physical mm errors",
              "zero_direction_policy": "count as degenerate and penalize 180 degrees; never silently drop",
              "ray_metrics": "predicted-origin ray is fully regressed; annotated-origin ray is explicitly conditional/oracle geometry, not full image-only tracking",
              "limitations": ["CNN weights are ImageNet features, not a pretrained gaze estimator; backbone never sees MPII labels.",
                              "All face/eye crops use the six supplied landmarks: oracle crop localization, not a face detector evaluation.",
                              "Landmarks and head pose baselines use annotations available at test time; no gaze target/direction is an input.",
                              "360 images/15 participants are a diagnostic sample, not a full-dataset SOTA replication.",
                              "Known per-participant calibration is allowed; no held-out gaze points are used for personalization.",
                              "Direct screen regression and ray projection are different heads and need not be geometrically self-consistent.",
                              "Head translation/face center are estimates; no phone-eye distance ground truth or mobile-domain validation."]}
    for name in ["train_mean"] + list(feature_sets):
        pred = np.zeros_like(target)
        for fold, (train, test) in enumerate(folds):
            if name == "train_mean":
                pred[test] = target[train].mean(axis=0)
            else:
                features, appearance_dims = feature_sets[name]
                pred[test] = fit_predict_fold(features, target, train, test, appearance_dims)
            for i in test:
                prediction_rows[i]["fold"] = fold
        metrics, samples = prediction_errors(pred, rows)
        per_subject = {}
        for subject in sorted(set(groups)):
            mask = np.flatnonzero(groups == subject)
            per_subject[subject], _ = prediction_errors(pred[mask], [rows[i] for i in mask])
        report["models"][name] = {"metrics": metrics, "per_subject": per_subject,
                                    "input_dimension": feature_sets[name][0].shape[1] if name != "train_mean" else 0}
        for item, sample in zip(prediction_rows, samples):
            item["models"][name] = sample
        print(name, "angular_deg", round(metrics["angular_error_deg"]["mean"], 3),
              "screen_mm", round(metrics["screen_direct_error_mm"]["mean"], 3), flush=True)
    write_json(output / "h1_models.json", report)
    write_jsonl(output / "model_predictions.jsonl", prediction_rows)
    comparisons = {}
    for left, right in [("landmarks_head_pose_ridge", "pixels32x24_ridge"),
                        ("landmarks_head_pose_ridge", "head_pose_only_ridge"),
                        ("face_eye_cnn_ridge", "face_cnn_ridge"),
                        ("appearance_head_pose_ridge", "face_eye_cnn_ridge"),
                        (MAIN_MODEL, "appearance_head_pose_ridge"),
                        (MAIN_MODEL, "landmarks_head_pose_ridge")]:
        if left not in report["models"] or right not in report["models"]:
            continue
        values = {}
        for metric in ("angular_error_deg", "screen_direct_error_mm"):
            delta = np.asarray([report["models"][left]["per_subject"][subject][metric]["mean"]
                                - report["models"][right]["per_subject"][subject][metric]["mean"] for subject in sorted(set(groups))])
            rng = np.random.default_rng(42)
            boot = delta[rng.integers(len(delta), size=(2000, len(delta)))].mean(axis=1)
            values[metric] = {"mean_left_minus_right": float(delta.mean()), "ci95": np.quantile(boot, [.025, .975]).tolist(),
                              "interpretation": "negative is better for left; paired participant bootstrap of fixed OOF errors; models not refit per draw"}
        comparisons[left + " minus " + right] = values
    report["modality_comparisons"] = comparisons
    write_json(output / "h1_models.json", report)
    chosen = MAIN_MODEL if use_cnn else "landmarks_head_pose_ridge"
    errors = sorted(prediction_rows, key=lambda r: r["models"][chosen]["angular_error_deg"], reverse=True)
    write_jsonl(output / "model_worst20.jsonl", errors[:20])
    return report
