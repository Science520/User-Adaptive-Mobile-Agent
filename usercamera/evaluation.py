import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .geometry import angular_errors_deg
from .io import read_jsonl, sha256, write_json, write_jsonl
from .metrics import classification_metrics, paired_cluster_bootstrap
from .synthetic import SCREEN_FEATURES, ACTION_FEATURES, USER_FEATURES


def grouped_folds(groups, max_folds=5):
    groups = np.asarray(groups)
    count = len(set(groups))
    if count < 3:
        raise ValueError("Evaluation requires >=3 independent groups; add participants/apps")
    splits = list(GroupKFold(n_splits=min(max_folds, count)).split(np.zeros(len(groups)), groups=groups))
    for train, test in splits:
        assert not set(groups[train]) & set(groups[test])
    return splits


def h1(root, output):
    path = Path(root) / "processed/mpii.jsonl"
    rows = read_jsonl(path)
    groups = np.asarray([r["subject_id"] for r in rows])
    if len(rows) < 20:
        raise ValueError("Too few MPIIFaceGaze images for even a baseline")
    features = []
    for row in rows:
        with Image.open(row["image_path"]) as im:
            # No landmarks, annotated rotation, calibration or target coordinates in input.
            feature = np.asarray(im.convert("L").resize((32, 24)), dtype=float).reshape(-1) / 255
        features.append(feature)
    features = np.asarray(features)
    target = np.asarray([r["gaze_direction"] + r["head_rvec"] + [r["face_camera_distance_proxy_mm"] / 1000]
                         + (np.asarray(r["gaze_screen_px"]) / r["screen_size_px"]).tolist() for r in rows])
    predictions, dummy = np.zeros_like(target), np.zeros_like(target)
    folds = []
    for index, (train, test) in enumerate(grouped_folds(groups)):
        model = make_pipeline(StandardScaler(), Ridge(alpha=100, solver="lsqr"))
        model.fit(features[train], target[train])
        predictions[test] = model.predict(features[test])
        dummy[test] = np.mean(target[train], axis=0)
        folds.append({"fold": index, "train_subjects": sorted(set(groups[train])),
                      "test_subjects": sorted(set(groups[test])), "train_n": len(train), "test_n": len(test)})

    def errors(pred):
        head = (Rotation.from_rotvec(pred[:, 3:6]).inv() * Rotation.from_rotvec(target[:, 3:6])).magnitude()
        return {"gaze_angular_error_deg": angular_errors_deg(pred[:, :3], target[:, :3]),
                "head_rotation_error_deg_estimated_label": np.degrees(head),
                "face_camera_distance_proxy_absolute_error_mm": abs(pred[:, 6] - target[:, 6]) * 1000,
                "normalized_xy_error_unit_square_diagonal": np.linalg.norm(pred[:, 7:9] - target[:, 7:9], axis=1) / np.sqrt(2)}
    model_errors, dummy_errors = errors(predictions), errors(dummy)
    report = {"hypothesis": "H1", "evidence_tier": "public_unimodal_baseline", "n": len(rows),
              "subjects": dict(Counter(groups)), "model": "32x24 grayscale pixels -> StandardScaler -> multioutput Ridge(alpha=100)",
              "input_features": "image pixels only; no annotated landmarks/pose/distance/gaze target",
              "metrics": {key: {"image_ridge_mean": float(value.mean()), "train_mean_baseline": float(dummy_errors[key].mean()),
                                 "image_ridge_median": float(np.median(value))} for key, value in model_errors.items()},
              "folds": folds, "input_sha256": sha256(path),
              "limitations": ["Small public sample, laptop camera domain; this is not a mobile-camera reliability validation.",
                              "Head pose and face center labels are estimates, not independent ground truth.",
                              "Face-camera distance is not phone-eye distance; no temporal changes are tested.",
                              "Low-resolution Ridge is a diagnostic baseline, not a reproduced state-of-the-art gaze encoder."],
              "H1_status": "baseline_measured_not_established", "H2_status": "not_tested", "H3_status": "not_tested"}
    write_json(Path(output) / "h1_public.json", report)
    write_jsonl(Path(output) / "h1_predictions.jsonl", [dict(id=row["id"], subject_id=row["subject_id"],
                 predicted_gaze_direction=predictions[i, :3].tolist(), target_gaze_direction=target[i, :3].tolist(),
                 errors={k: float(v[i]) for k, v in model_errors.items()}) for i, row in enumerate(rows)])
    return report


def matrix(rows, modalities):
    names = {"S": ("screen", SCREEN_FEATURES), "A": ("actions", ACTION_FEATURES), "U": ("user", USER_FEATURES)}
    vectors = []
    for row in rows:
        vector = []
        for modality in modalities:
            key, columns = names[modality]
            vector.extend(row[key][column] for column in columns)
        vectors.append(vector)
    result = np.asarray(vectors, dtype=float)
    if not np.isfinite(result).all():
        raise ValueError("Nonfinite model features")
    return result


def ablate(rows, target, group_key="group_id", seed=42):
    y = np.asarray([row[target] for row in rows])
    labels = sorted(set(y))
    if len(labels) < 2:
        raise ValueError(f"Only one {target} class; cannot evaluate")
    groups = np.asarray([row[group_key] for row in rows])
    splits = grouped_folds(groups)
    probabilities, metrics = {}, {}
    variants = {"S": "S", "S+A": "SA", "S+U": "SU", "S+A+U": "SAU", "S+A+shuffled_U": "SAU", "majority": "S"}
    for name, modalities in variants.items():
        x = matrix(rows, modalities)
        probability = np.zeros((len(rows), len(labels)))
        for fold, (train, test) in enumerate(splits):
            train_x, test_x = x[train].copy(), x[test].copy()
            if name == "S+A+shuffled_U":
                rng = np.random.default_rng(seed + fold)
                # Permute within each split only; no test features influence fitting.
                train_x[:, -len(USER_FEATURES):] = train_x[rng.permutation(len(train)), -len(USER_FEATURES):]
                test_x[:, -len(USER_FEATURES):] = test_x[rng.permutation(len(test)), -len(USER_FEATURES):]
            if name == "majority":
                model = DummyClassifier(strategy="prior")
            else:
                model = RandomForestClassifier(n_estimators=100, min_samples_leaf=5, max_depth=12,
                                               class_weight="balanced", random_state=seed, n_jobs=2)
            model.fit(train_x, y[train])
            predicted = model.predict_proba(test_x)
            for j, label in enumerate(model.classes_):
                probability[test, labels.index(label)] = predicted[:, j]
        probabilities[name] = probability
        metrics[name] = classification_metrics(y, probability, labels)
        if target != "intervention":
            metrics[name].pop("unnecessary_intervention_rate", None)
    pred = {k: np.asarray(labels)[v.argmax(axis=1)] for k, v in probabilities.items()}
    comparisons = {}
    for control in ("S+A", "S+A+shuffled_U"):
        comparison = paired_cluster_bootstrap(y, pred["S+A+U"], pred[control], groups, labels, seed)
        comparison["point_difference"] = metrics["S+A+U"]["macro_f1"] - metrics[control]["macro_f1"]
        comparisons["S+A+U minus " + control] = comparison
    folds = [{"fold": i, "train_groups": sorted(set(groups[a])), "test_groups": sorted(set(groups[b])),
              "train_classes": dict(Counter(y[a])), "test_classes": dict(Counter(y[b]))} for i, (a, b) in enumerate(splits)]
    return {"target": target, "class_counts": dict(Counter(y)), "metrics": metrics,
            "paired_comparisons": comparisons, "folds": folds}, pred, probabilities


def evaluate_synthetic(root, output, seed=42):
    path = Path(root) / "synthetic/scenarios.jsonl"
    rows = read_jsonl(path)
    if not rows or any(r.get("evidence_tier") != "synthetic_proxy" for r in rows):
        raise ValueError("Synthetic evaluation accepts explicitly marked proxy rows only")
    # A base screenshot, including aliases with identical image content, must stay in one group.
    assignments = {}
    for row in rows:
        for key in (row["source_screen_id"], row["source_image_sha256"]):
            if key in assignments and assignments[key] != row["group_id"]:
                raise ValueError("Identical source screen appears in different groups")
            assignments[key] = row["group_id"]
    report = {"evidence_tier": "synthetic_proxy", "n": len(rows), "seed": seed,
              "input_sha256": sha256(path), "feature_sets": {"S": SCREEN_FEATURES, "A": ACTION_FEATURES, "U": USER_FEATURES},
              "model": "RandomForest(100 trees, depth<=12, leaf>=5); fixed settings, grouped OOF",
              "H2_status": "synthetic_mechanism_only_not_real_validation", "H3_status": "synthetic_rule_only_not_real_validation",
              "limitations": ["User distance is simulated and the proxy label explicitly depends on it: gain is designed into the task.",
                              "Screen features are renderer metadata, not predictions of a trained GUI image encoder.",
                              "No random pairing of public faces and screens, no real camera action stream.",
                              "No evidence of intervention effectiveness; zoom/hint/none are heuristic labels.",
                              "PPI and thresholds are experiment parameters, not calibrated human perceptual thresholds.",
                              "Random Forest probability ECE is reported without calibration; no validation-set tuning."]}
    output_rows = [dict(id=r["id"], group_id=r["group_id"]) for r in rows]
    for target in ("difficulty", "intervention"):
        result, predictions, probabilities = ablate(rows, target, seed=seed)
        report[target] = result
        for i, row in enumerate(output_rows):
            row[target] = {"true": rows[i][target], "predictions": {k: str(v[i]) for k, v in predictions.items()},
                           "probabilities": {k: v[i].tolist() for k, v in probabilities.items()},
                           "probability_labels": sorted(set(r[target] for r in rows))}
    write_json(Path(output) / "h2_h3_synthetic.json", report)
    write_jsonl(Path(output) / "synthetic_predictions.jsonl", output_rows)
    return report


def grounding(root, output, predictions_path=None):
    """Scores external model predictions or explicitly marked center-point sanity baseline."""
    tasks = read_jsonl(Path(root) / "processed/funui_tasks.jsonl")
    predictions = {}
    if predictions_path:
        for row in read_jsonl(predictions_path):
            if row["id"] in predictions:
                raise ValueError("Duplicate grounding prediction ID")
            predictions[row["id"]] = row
    eligible = [t for t in tasks if t.get("positive_grounding") and t.get("bbox_valid") and not t.get("question_contains_box")]
    if not eligible:
        raise ValueError("No eligible positive grounding tasks")
    hits, missing = [], 0
    for task in eligible:
        if predictions_path:
            pred = predictions.get(task["id"])
            if pred is None:
                missing += 1
                hits.append(False)
                continue
            point = np.asarray(pred["point_px"], dtype=float)
            if point.shape != (2,) or not np.isfinite(point).all():
                raise ValueError("Expected finite point_px [x,y]")
        else:
            with Image.open(task["image_path"]) as im:
                point = np.asarray(im.size) / 2
        x1, y1, x2, y2 = task["bbox_xyxy"]
        hits.append(x1 <= point[0] <= x2 and y1 <= point[1] <= y2)
    report = {"task": "FunUI positive grounding", "eligible": len(eligible), "missing_predictions_counted_wrong": missing,
              "point_accuracy": float(np.mean(hits)), "model": "external point predictions" if predictions_path else "screen center sanity baseline",
              "excluded": "negative/nonbox answers, invalid/outside boxes, and questions containing bounding box coordinates",
              "unknown_prediction_ids": sorted(set(predictions) - {t["id"] for t in eligible}),
              "external_predictions_scored": bool(predictions_path),
              "note": "Center baseline checks scoring only. Raw QA/referring/summarization are preserved but not model-evaluated."}
    write_json(Path(output) / "screen_grounding.json", report)
    return report


def make_report(root, output):
    output = Path(output)
    for report_name, input_name in [("h1_public.json", "processed/mpii.jsonl"),
                                    ("h2_h3_synthetic.json", "synthetic/scenarios.jsonl")]:
        report_path, input_path = output / report_name, Path(root) / input_name
        if report_path.exists():
            saved = json.loads(report_path.read_text())
            if not input_path.exists() or saved.get("input_sha256") != sha256(input_path):
                raise ValueError(f"Stale/mixed experiment report: {report_path}; rerun evaluation or use a separate --output")
    audit_path = Path(root) / "processed/audit.json"
    audit = json.loads(audit_path.read_text()) if audit_path.exists() else {}
    lines = ["# 第一阶段实验结果", "", "本报告由实际运行生成。公开单模态验证、合成代理任务和真实同步实验分别记录。", "",
             "## 数据检查", "", "```json", json.dumps(audit, ensure_ascii=False, indent=2), "```", ""]
    h1_path = output / "h1_public.json"
    if h1_path.exists():
        h = json.loads(h1_path.read_text())
        lines += ["## H1：公开人脸图像基线", "", f"{h['n']} 张图像，{len(h['subjects'])} 名参与者，按参与者分组交叉验证。输入仅为低分辨率灰度像素。", "",
                  "| 指标（越低越好） | 图像 Ridge | 训练集均值基线 |", "| --- | ---: | ---: |"]
        for metric, value in h["metrics"].items():
            lines.append(f"| {metric} | {value['image_ridge_mean']:.4f} | {value['train_mean_baseline']:.4f} |")
        lines += ["", "这只记录图像基线的误差；不据此宣称手机摄像头可靠性成立。头姿/距离代理标签来自估计，距离不是手机—眼睛距离真值。", ""]
    synthetic_path = output / "h2_h3_synthetic.json"
    if synthetic_path.exists():
        h = json.loads(synthetic_path.read_text())
        lines += ["## H2 / H3：合成代理验证", "", f"{h['n']} 条源于公开界面素材的受控重绘样本。User 特征为模拟几何量，没有将随机人脸与屏幕配成真实数据。", "",
                  "距离进入了代理标签公式，因此性能提升只能验证预设机制和实验管道。", ""]
        for target in ("difficulty", "intervention"):
            lines += [f"### {target}", "", "| 模态 | Macro-F1 | Balanced acc. | AUROC | ECE |", "| --- | ---: | ---: | ---: | ---: |"]
            for name, m in h[target]["metrics"].items():
                auc = f"{m['auroc_ovr']:.3f}" if m["auroc_ovr"] is not None else "N/A"
                lines.append(f"| {name} | {m['macro_f1']:.3f} | {m['balanced_accuracy']:.3f} | {auc} | {m['ece_10_bins']:.3f} |")
            for name, comparison in h[target]["paired_comparisons"].items():
                lo, hi = comparison["ci95"]
                lines += ["", f"{name}：ΔMacro-F1={comparison['point_difference']:.3f}，按 App 分组的配对 bootstrap 95% 区间 [{lo:.3f}, {hi:.3f}]。"]
            if target == "intervention":
                m = h[target]["metrics"]["S+A+U"]
                lines += ["", f"无需干预样本上的错误干预率：{m['unnecessary_intervention_rate']:.3f}。"]
            lines += [""]
    h1_status = "已测量公开图像基线；手机场景、连续行为与独立距离真值仍未验证。" if h1_path.exists() else "本次运行未测量公开人脸图像基线。"
    lines += ["## 科学结论边界", "", "- H1：" + h1_status,
              "- H2：仅完成合成标签机制验证；真实同步用户上的互补增益待检验。",
              "- H3：仅完成启发式干预类别预测；真实干预有效性仍需受控用户实验。",
              "", "完整指标、预测、分组清单和数据哈希见同目录 JSON/JSONL 文件。"]
    output.mkdir(parents=True, exist_ok=True)
    (output / "RESULTS.md").write_text("\n".join(lines) + "\n")
    return str(output / "RESULTS.md")
