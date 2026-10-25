"""Static scientific plots of real MPIIFaceGaze samples and held-out predictions."""
import json
import os
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from .camera_screen_geometry import screen_corners
from .io import read_jsonl, sha256, write_json
from .mpii_models import MAIN_MODEL, crop_boxes


SHORT = {"train_mean": "Train mean", "pixels32x24_ridge": "Pixels 32x24", "landmarks_only_ridge": "Landmarks",
         "head_pose_only_ridge": "Head pose", "landmarks_head_pose_ridge": "Landmarks+pose",
         "calibration_only_ridge": "Calibration", "face_cnn_ridge": "Face CNN", "face_eye_cnn_ridge": "Face+eyes CNN",
         "appearance_head_pose_ridge": "CNN+pose", MAIN_MODEL: "CNN+pose+cal"}


def pyplot():
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "usercamera-mpl"))
    os.environ.setdefault("XDG_CACHE_HOME", str(Path(tempfile.gettempdir()) / "usercamera-xdg"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def visualize(root="data", output="reports/mpii_geometry", count=30, model=MAIN_MODEL):
    plt = pyplot()
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    root, output = Path(root), Path(output)
    rows = read_jsonl(root / "processed/mpii.jsonl")
    predictions = {r["id"]: r for r in read_jsonl(output / "model_predictions.jsonl")}
    geometry = {r["id"]: r for r in read_jsonl(output / "geometry_samples.jsonl")}
    source_hash = sha256(root / "processed/mpii.jsonl")
    for name in ("geometry_consistency.json", "h1_models.json"):
        if json.loads((output / name).read_text())["input_sha256"] != source_hash:
            raise ValueError("Cannot visualize stale or mixed geometry/model results")
    if count <= 0 or count > len(rows):
        raise ValueError("Invalid real-sample visualization count")
    if model not in predictions[rows[0]["id"]]["models"]:
        raise ValueError("Requested visualization model did not run")
    subject_rows = {s: [r for r in rows if r["subject_id"] == s] for s in sorted({r["subject_id"] for r in rows})}
    rng = np.random.default_rng(42)
    for values in subject_rows.values():
        rng.shuffle(values)
    selected = []
    # Participant-balanced selection, independent of prediction errors/labels.
    while len(selected) < count:
        for values in subject_rows.values():
            if values and len(selected) < count:
                selected.append(values.pop())
    destination = output / "visualizations"
    destination.mkdir(parents=True, exist_ok=True)
    images, manifest = [], []
    for index, row in enumerate(selected):
        geo, pred = geometry[row["id"]], predictions[row["id"]]
        current = pred["models"][model]
        fig = plt.figure(figsize=(14, 10), constrained_layout=True)
        face_ax = fig.add_subplot(2, 2, 1)
        with Image.open(row["image_path"]) as image:
            face_ax.imshow(image)
        points = np.asarray(row["landmarks_2d"])
        face_ax.scatter(points[:, 0], points[:, 1], c=np.arange(6), cmap="tab10", s=25, edgecolors="white")
        for i, (x, y) in enumerate(points):
            face_ax.text(x+3, y-4, str(i+1), color="yellow", fontsize=10)
        b = crop_boxes(row)[0]
        face_ax.set_xlim(b[0], b[2]); face_ax.set_ylim(b[3], b[1])
        face_ax.set_title("Real face + six supplied landmarks (oracle crop)")
        face_ax.set_xlabel("raw camera image x [px]"); face_ax.set_ylabel("raw camera image y [px]")
        screen_ax = fig.add_subplot(2, 2, 2)
        s = row["calibration"]["screen"]
        screen_ax.set_facecolor("#fafafa")
        target = np.asarray(geo["official_target_mm"])
        recon = np.asarray(geo["screen_xyz_mm"])[:2]
        screen_ax.scatter(*target, marker="x", s=110, c="red", label="Official known target")
        screen_ax.scatter(*recon, marker="o", s=180, facecolors="none", edgecolors="green", label="Label-ray reconstruction")
        p = np.asarray(current["screen_direct_px"]) / [s["width_pixel"], s["height_pixel"]] * [s["width_mm"], s["height_mm"]]
        screen_ax.scatter(*p, marker="+", s=120, c="blue", label="Held-out direct screen head")
        screen_ax.plot([target[0], p[0]], [target[1], p[1]], c="blue", alpha=.4)
        screen_ax.set_xlim(-.02*s["width_mm"], 1.02*s["width_mm"])
        screen_ax.set_ylim(1.02*s["height_mm"], -.02*s["height_mm"])
        screen_ax.set_aspect("equal")
        screen_ax.set_xlabel("screen x [mm]"); screen_ax.set_ylabel("screen y [mm], downward")
        screen_ax.set_title(f"Geometry residual {geo['reconstruction_error_px']:.3g} px (NOT model accuracy)")
        screen_ax.legend(loc="lower right", fontsize=8)
        axis3d = fig.add_subplot(2, 2, 3, projection="3d")
        corners = screen_corners(row["calibration"])
        axis3d.add_collection3d(Poly3DCollection([corners], alpha=.3, facecolor="cyan", edgecolor="teal"))
        center, target3 = np.asarray(row["face_center_mm"]), np.asarray(row["gaze_target_mm"])
        axis3d.scatter(0, 0, 0, c="black", marker="^", s=70, label="Camera optical center")
        axis3d.scatter(*center, c="purple", s=50, label="Annotated face center")
        axis3d.scatter(*target3, c="red", marker="x", s=70, label="Known target")
        segment = np.stack([center, target3])
        axis3d.plot(*segment.T, c="green", label="Label-derived gaze ray")
        origin = np.asarray(current["predicted_face_center_mm"])
        direction = np.asarray(current["predicted_gaze_direction"])
        end = origin + direction * np.linalg.norm(target3-center)
        axis3d.plot(*np.stack([origin, end]).T, c="orange", linestyle="--", label="Model ray / model origin")
        for i, color in enumerate(["red", "green", "blue"]):
            end_axis = np.eye(3)[i] * 45
            axis3d.plot(*np.stack([np.zeros(3), end_axis]).T, c=color)
        axis3d.set_xlabel("X [mm]", labelpad=1); axis3d.set_ylabel("Y [mm]", labelpad=1); axis3d.set_zlabel("Z [mm]", labelpad=1)
        from matplotlib.ticker import MaxNLocator
        for axis in (axis3d.xaxis, axis3d.yaxis, axis3d.zaxis):
            axis.set_major_locator(MaxNLocator(4))
        axis3d.tick_params(labelsize=7, pad=1)
        axis3d.set_title("Camera/face/screen in ONE camera coordinate system")
        scene = np.vstack([corners, np.zeros(3), center, origin, end])
        axis3d.auto_scale_xyz(scene[:, 0], scene[:, 1], scene[:, 2])
        axis3d.set_box_aspect(np.maximum(np.ptp(scene, axis=0), 1), zoom=.8)
        axis3d.legend(fontsize=7, loc="upper left")
        axis3d.view_init(elev=20, azim=-65)
        table_ax = fig.add_subplot(2, 2, 4)
        table_ax.axis("off")
        table = [[SHORT.get(name, name), f"{values['angular_error_deg']:.2f}", f"{values['screen_direct_error_mm']:.2f}"]
                 for name, values in pred["models"].items()]
        t = table_ax.table(cellText=table, colLabels=["Held-out model", "Gaze [deg]", "Direct screen [mm]"],
                           cellLoc="left", loc="center", colWidths=[.49, .24, .27])
        t.auto_set_font_size(False); t.set_fontsize(9); t.scale(1, 1.6)
        table_ax.set_title(f"Official pixel target: {row['gaze_screen_px']}\nCurrent model: {SHORT.get(model, model)}")
        table_ax.text(0, .02, "Reconstruction uses known 3D labels.\nModel rows use held-out participants; crops use annotated landmarks.", fontsize=8)
        fig.suptitle(f"MPIIFaceGaze {row['subject_id']} | {Path(row['id']).name} | sample {index+1}/{count}", fontsize=15)
        path = destination / f"sample_{index:02d}_{row['subject_id']}.png"
        fig.savefig(path, dpi=125); plt.close(fig)
        images.append(path)
        manifest.append({"id": row["id"], "subject_id": row["subject_id"], "image": str(path.relative_to(output)),
                         "original_image_sha256": sha256(row["image_path"]), "fold": pred["fold"], "model": model})
    distributions = []
    model_report = json.loads((output / "h1_models.json").read_text())
    for subject in sorted(subject_rows):
        local = [r for r in rows if r["subject_id"] == subject]
        label_path = root / "raw/mpiifacegaze/Data" / subject / (subject+".txt")
        all_points = np.asarray([[float(x) for x in line.split()[1:3]] for line in label_path.read_text().splitlines() if line.strip()])
        fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
        size = np.asarray(local[0]["screen_size_px"])
        axes[0].scatter(*(all_points/size).T, c="gray", s=4, alpha=.15, label="All local labels (photos not all local)")
        target = np.asarray([r["gaze_screen_px"] for r in local]) / size
        predicted = np.asarray([predictions[r["id"]]["models"][model]["screen_direct_px"] for r in local]) / size
        axes[0].scatter(*target.T, c="red", s=15, label="360-image subset targets")
        axes[0].quiver(*target.T, *(predicted-target).T, angles="xy", scale_units="xy", scale=1, width=.003, color="blue", alpha=.6)
        axes[0].plot([0, 1, 1, 0, 0], [0, 0, 1, 1, 0], c="black")
        axes[0].invert_yaxis(); axes[0].set_aspect("equal")
        axes[0].set_xlabel("screen x / width"); axes[0].set_ylabel("screen y / height")
        axes[0].set_title("Targets + held-out direct-screen error vectors")
        axes[0].legend(fontsize=7)
        names = list(model_report["models"])
        errors = [model_report["models"][n]["per_subject"][subject]["angular_error_deg"]["mean"] for n in names]
        axes[1].barh([SHORT.get(n, n) for n in names], errors)
        axes[1].invert_yaxis(); axes[1].set_xlabel("mean held-out gaze angular error [deg]")
        axes[1].set_title("Per-participant model errors")
        fig.suptitle(subject + " | " + SHORT.get(model, model))
        path = destination / f"distribution_{subject}.png"
        fig.savefig(path, dpi=130); plt.close(fig)
        distributions.append(str(path.relative_to(output)))
    sheet = Image.new("RGB", (3*560, int(np.ceil(count/3))*400), "white")
    for i, path in enumerate(images):
        with Image.open(path) as image:
            tile = image.copy(); tile.thumbnail((560, 400))
        sheet.paste(tile, ((i%3)*560, (i//3)*400))
    sheet.save(destination / "contact_sheet.jpg", quality=88)
    write_json(output / "visualization_manifest.json", {"input_sha256": source_hash, "real_samples": count,
                "selection": "seed42 participant-round-robin, independent of errors", "samples": manifest, "distributions": distributions})
    html = ['<!doctype html><meta charset="utf-8"><title>MPIIFaceGaze validation</title>',
            '<h1>Real MPIIFaceGaze geometry and held-out predictions</h1><p>Label-ray reconstruction is not model accuracy. Crops use supplied landmarks.</p>',
            '<p>Image source: <a href="https://doi.org/10.18419/DARUS-3240">MPIIFaceGaze (Bulling, 2023; Zhang et al., 2017)</a>. Derived face-image figures retain <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/">CC BY-NC-SA 4.0</a> terms.</p>']
    for path in images:
        name = path.name
        html.append(f'<p><a href="{name}"><img src="{name}" width="900" alt="{name}"></a></p>')
    for path in distributions:
        name = Path(path).name
        html.append(f'<p><a href="{name}"><img src="{name}" width="900" alt="{name}"></a></p>')
    (destination / "index.html").write_text("\n".join(html))
    return {"real_sample_figures": count, "participant_distributions": len(distributions), "index": str(destination / "index.html")}
