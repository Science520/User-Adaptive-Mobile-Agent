import numpy as np
from sklearn.metrics import balanced_accuracy_score, f1_score, roc_auc_score, confusion_matrix


def classification_metrics(y, probabilities, labels):
    y = np.asarray(y)
    probabilities = np.asarray(probabilities)
    pred = np.asarray(labels)[np.argmax(probabilities, axis=1)]
    correct = pred == y
    confidence = probabilities.max(axis=1)
    ece = 0.0
    for i in range(10):
        mask = (confidence >= i / 10) & (confidence < (i + 1) / 10 if i < 9 else confidence <= 1)
        if mask.any():
            ece += mask.mean() * abs(correct[mask].mean() - confidence[mask].mean())
    auroc = None
    if len(set(y)) == len(labels):
        if len(labels) == 2:
            auroc = roc_auc_score(y == labels[1], probabilities[:, 1])
        else:
            auroc = roc_auc_score(y, probabilities, labels=labels, multi_class="ovr", average="macro")
    result = {"macro_f1": f1_score(y, pred, labels=labels, average="macro", zero_division=0),
              "balanced_accuracy": balanced_accuracy_score(y, pred), "auroc_ovr": auroc,
              "ece_10_bins": float(ece), "labels": labels,
              "confusion_matrix": confusion_matrix(y, pred, labels=labels).tolist()}
    none = y == "none"
    if "none" in labels:
        result["unnecessary_intervention_rate"] = float(np.mean(pred[none] != "none")) if none.any() else None
    return result


def paired_cluster_bootstrap(y, left, right, groups, labels, seed=42, repetitions=500):
    """Re-sample held-out groups together for both systems; never iid bootstrap variants."""
    y, left, right, groups = map(np.asarray, (y, left, right, groups))
    unique = np.unique(groups)
    if len(unique) < 2:
        return {"ci95": None, "reason": "fewer than two independent groups"}
    rng = np.random.default_rng(seed)
    blocks = {group: np.flatnonzero(groups == group) for group in unique}
    differences = []
    for _ in range(repetitions):
        idx = np.concatenate([blocks[g] for g in rng.choice(unique, len(unique), replace=True)])
        a = f1_score(y[idx], left[idx], labels=labels, average="macro", zero_division=0)
        b = f1_score(y[idx], right[idx], labels=labels, average="macro", zero_division=0)
        differences.append(a - b)
    return {"metric": "macro_f1(left)-macro_f1(right)", "resampling_unit": "held-out group",
            "groups": len(unique), "repetitions": repetitions,
            "ci95": np.quantile(differences, [0.025, 0.975]).tolist(),
            "limitation": "OOF cluster bootstrap is descriptive; training is not repeated per bootstrap"}
