"""MPIIFaceGaze rigid camera/screen geometry, in millimetres and column vectors.

X_camera = R_screen_to_camera @ [x_screen_mm, y_screen_mm, 0] + t.
Screen pixels are continuous coordinates, top-left origin, x right and y down.
No per-subject fitting, flips, offsets or label correction is performed.
"""
from pathlib import Path
import json

import numpy as np
from scipy.io import loadmat
from scipy.spatial.transform import Rotation

from .geometry import gaze_vector, ray_screen_intersection
from .io import read_jsonl, sha256, write_json, write_jsonl


def finite_array(value, shape, name):
    a = np.asarray(value, dtype=float)
    if a.size != int(np.prod(shape)) or not np.isfinite(a).all():
        raise ValueError(f"Invalid {name}: expected {shape}, finite values")
    return a.reshape(shape)


def load_calibration(folder, subject_id):
    folder = Path(folder)
    files = {name: folder / name for name in ("Camera.mat", "monitorPose.mat", "screenSize.mat")}
    if not files["screenSize.mat"].exists() and (folder / "creenSize.mat").exists():
        files["screenSize.mat"] = folder / "creenSize.mat"
    camera, monitor, size = [loadmat(files[name]) for name in files]
    rotation_key = next((k for k in ("rvects", "rvecs", "rvec") if k in monitor), None)
    if rotation_key is None:
        raise ValueError("monitorPose.mat has no supported Rodrigues vector field")
    rvec = finite_array(monitor[rotation_key], (3,), "screen Rodrigues vector")
    t = finite_array(monitor["tvecs"], (3,), "screen translation")
    R = Rotation.from_rotvec(rvec).as_matrix()
    K = finite_array(camera["cameraMatrix"], (3, 3), "camera intrinsics")
    if K[0, 0] <= 0 or K[1, 1] <= 0 or not np.allclose(K[2], [0, 0, 1]):
        raise ValueError("Invalid pinhole intrinsics")
    dimensions = {k: float(np.asarray(size[k]).squeeze()) for k in ("width_mm", "height_mm", "width_pixel", "height_pixel")}
    if any(not np.isfinite(x) or x <= 0 for x in dimensions.values()):
        raise ValueError("Screen dimensions must be positive and finite")
    dist = np.asarray(camera["distCoeffs"], dtype=float).reshape(-1)
    if not np.isfinite(dist).all():
        raise ValueError("Nonfinite distortion coefficients")
    transform = np.eye(4)
    transform[:3, :3], transform[:3, 3] = R, t
    return {
        "schema_version": "mpii-camera-screen-v2", "subject_id": subject_id,
        "units": {"length": "mm", "pixel": "px", "rotation_vector": "radian"},
        "camera": {"K": K.tolist(), "distortion_coefficients": dist.tolist(),
                   "calibration_rms_px": float(np.asarray(camera["retval"]).squeeze()),
                   "axes": "+X image right; +Y image down; +Z forward from optical center",
                   "board_pose_count": int(np.asarray(camera.get("rvecs", [])).size // 3),
                   "board_poses_note": "Camera.mat rvecs/tvecs describe calibration-board views, NOT the monitor pose"},
        "screen": {**dimensions, "rvec_screen_to_camera": rvec.tolist(), "rotation_field_in_mat": rotation_key,
                   "R_screen_to_camera": R.tolist(), "t_screen_to_camera_mm": t.tolist(),
                   "T_screen_to_camera": transform.tolist(), "T_camera_to_screen": np.linalg.inv(transform).tolist(),
                   "origin": "top-left active display; x right, y down, z=0",
                   "normal_camera": R[:, 2].tolist(),
                   "pixel_conversion": "x_mm=x_px*width_mm/width_pixel; y_mm=y_px*height_mm/height_pixel; no +1/-1 correction"},
        "convention_evidence": "Fixed screen-to-camera convention tested against official 2D/3D labels; not per-subject fitted",
        "source_files": {name: {"path": str(path.resolve()), "sha256": sha256(path)} for name, path in files.items()},
    }


def screen_to_camera(xyz_mm, calibration):
    screen = calibration["screen"]
    R, t = np.asarray(screen["R_screen_to_camera"]), np.asarray(screen["t_screen_to_camera_mm"])
    xyz = np.asarray(xyz_mm, dtype=float)
    return xyz @ R.T + t


def camera_to_screen(xyz_mm, calibration):
    screen = calibration["screen"]
    R, t = np.asarray(screen["R_screen_to_camera"]), np.asarray(screen["t_screen_to_camera_mm"])
    return (np.asarray(xyz_mm, dtype=float) - t) @ R


def mm_to_px(xy_mm, calibration):
    s = calibration["screen"]
    return np.asarray(xy_mm) * [s["width_pixel"] / s["width_mm"], s["height_pixel"] / s["height_mm"]]


def px_to_mm(xy_px, calibration):
    s = calibration["screen"]
    return np.asarray(xy_px) * [s["width_mm"] / s["width_pixel"], s["height_mm"] / s["height_pixel"]]


def intersect_gaze(origin_camera_mm, direction_camera, calibration):
    origin = finite_array(origin_camera_mm, (3,), "gaze origin")
    direction = finite_array(direction_camera, (3,), "gaze direction")
    if np.linalg.norm(direction) < 1e-12:
        raise ValueError("Zero-length gaze direction")
    s = calibration["screen"]
    intersection = ray_screen_intersection(origin, direction, s["t_screen_to_camera_mm"], s["normal_camera"])
    screen_xyz = camera_to_screen(intersection, calibration)
    return {"intersection_camera_mm": intersection.tolist(), "screen_xyz_mm": screen_xyz.tolist(),
            "screen_xy_px": mm_to_px(screen_xyz[:2], calibration).tolist()}


def screen_corners(calibration):
    s = calibration["screen"]
    return screen_to_camera([[0, 0, 0], [s["width_mm"], 0, 0],
                             [s["width_mm"], s["height_mm"], 0], [0, s["height_mm"], 0]], calibration)


def describe(values):
    a = np.asarray(values, dtype=float)
    if not len(a):
        return {"n": 0, "mean": None, "median": None, "p95": None, "max": None}
    return {"n": len(a), "mean": float(a.mean()), "median": float(np.median(a)),
            "p95": float(np.quantile(a, .95)), "max": float(a.max())}


def convention_diagnostics(row):
    """Report deliberately wrong alternatives; never select one using test labels."""
    c, target = row["calibration"], np.asarray(row["gaze_target_mm"])
    s = c["screen"]
    R, t = np.asarray(s["R_screen_to_camera"]), np.asarray(s["t_screen_to_camera_mm"])
    q = camera_to_screen(target, c)
    normal = mm_to_px(q[:2], c)
    alternatives = {
        "fixed_documented_convention": normal,
        "wrong_rotation_transpose": mm_to_px((R @ (target - t))[:2], c),
        "wrong_transform_direction": mm_to_px((R @ target + t)[:2], c),
        "wrong_center_origin": normal + np.array([s["width_pixel"], s["height_pixel"]]) / 2,
        "wrong_horizontal_flip": [s["width_pixel"] - normal[0], normal[1]],
        "wrong_vertical_flip": [normal[0], s["height_pixel"] - normal[1]],
        "wrong_mm_as_cm_scale": normal * 10,
        "wrong_one_based_offset": normal + 1,
        "wrong_W_minus_1_pixel_scale": q[:2] * [(s["width_pixel"]-1)/s["width_mm"], (s["height_pixel"]-1)/s["height_mm"]],
    }
    return {key: float(np.linalg.norm(np.asarray(point) - row["gaze_screen_px"])) for key, point in alternatives.items()}


def validate_geometry(root="data", output="reports/mpii_geometry", tolerance_px=.01, tolerance_mm=.001):
    root, output = Path(root), Path(output)
    path = root / "processed/mpii.jsonl"
    rows = read_jsonl(path)
    results, subjects = [], {}
    for row in rows:
        result = {"id": row["id"], "subject_id": row["subject_id"], "type": "annotation_geometry_consistency_not_model_prediction"}
        c = row["calibration"]
        target, origin = np.asarray(row["gaze_target_mm"]), np.asarray(row["face_center_mm"])
        try:
            direction = gaze_vector(origin, target)
            reconstruction = intersect_gaze(origin, direction, c)
            xyz, pixel = np.asarray(reconstruction["screen_xyz_mm"]), np.asarray(reconstruction["screen_xy_px"])
            expected_mm = px_to_mm(row["gaze_screen_px"], c)
            pixel_error = float(np.linalg.norm(pixel - row["gaze_screen_px"]))
            physical_error = float(np.linalg.norm(xyz[:2] - expected_mm))
            plane_residual = float(abs(camera_to_screen(target, c)[2]))
            s = c["screen"]
            on_screen = bool(0 <= pixel[0] <= s["width_pixel"] and 0 <= pixel[1] <= s["height_pixel"])
            result.update(reconstruction, official_target_px=row["gaze_screen_px"],
                          official_target_mm=expected_mm.tolist(), gaze_ray_direction=direction.tolist(),
                          reconstruction_error_px=pixel_error, reconstruction_error_mm=physical_error,
                          target_plane_residual_mm=plane_residual,
                          ray_target_distance_mm=float(np.linalg.norm(np.asarray(reconstruction["intersection_camera_mm"]) - target)),
                          official_target_within_display=on_screen,
                          consistent=pixel_error <= tolerance_px and plane_residual <= tolerance_mm,
                          diagnostics_px=convention_diagnostics(row))
        except ValueError as exc:
            result.update(consistent=False, failure=str(exc))
        results.append(result)
    for subject in sorted({r["subject_id"] for r in results}):
        samples = [r for r in results if r["subject_id"] == subject]
        valid = [r for r in samples if "failure" not in r]
        subjects[subject] = {"n": len(samples), "inconsistent": sum(not r["consistent"] for r in samples),
                             "outside_display": sum(not r["official_target_within_display"] for r in valid),
                             "reconstruction_px": describe([r["reconstruction_error_px"] for r in valid]),
                             "reconstruction_mm": describe([r["reconstruction_error_mm"] for r in valid]),
                             "plane_residual_mm": describe([r["target_plane_residual_mm"] for r in valid]),
                             "convention_diagnostic_mean_error_px": {key: float(np.mean([r["diagnostics_px"][key] for r in valid]))
                                                                    for key in valid[0]["diagnostics_px"]} if valid else {}}
    report = {"task": "Camera–Screen Geometry Validation", "input_sha256": sha256(path),
              "is_gaze_model_accuracy": False, "n": len(results), "tolerance_px": tolerance_px, "tolerance_mm": tolerance_mm,
              "convention": "Xc=Rsc@Xs+tsc; top-left origin, x right/y down; mm; Rodrigues radians; continuous pixels",
              "subjects": subjects, "inconsistent_ids": [r["id"] for r in results if not r["consistent"]],
              "overall_reconstruction_px": describe([r["reconstruction_error_px"] for r in results if "failure" not in r]),
              "overall_reconstruction_mm": describe([r["reconstruction_error_mm"] for r in results if "failure" not in r]),
              "interpretation": "Reconstructs label-derived rays. Tiny residuals check implementation/calibration consistency only, not gaze prediction, independent accuracy, or physical calibration accuracy."}
    write_json(output / "geometry_consistency.json", report)
    write_jsonl(output / "geometry_samples.jsonl", results)
    write_jsonl(output / "geometry_errors.jsonl", [r for r in results if not r["consistent"]])
    # All annotation rows can be checked geometrically without downloading their images.
    calibrations = json.loads((root / "processed/mpii_calibrations.json").read_text())
    full, warnings = {}, []
    for annotation in sorted((root / "raw/mpiifacegaze").rglob("p[0-9][0-9].txt")):
        c = calibrations[annotation.stem]
        records, paths = [], []
        for line in annotation.read_text().splitlines():
            parts = line.split()
            if len(parts) != 28:
                continue
            a = np.asarray(parts[1:27], dtype=float)
            if np.isfinite(a).all():
                records.append(a)
                paths.append(str(annotation.parent.relative_to(root / "raw/mpiifacegaze") / parts[0]))
        a = np.asarray(records)
        origins, targets = a[:, 20:23], a[:, 23:26]
        vectors = targets - origins
        normal, t = np.asarray(c["screen"]["normal_camera"]), np.asarray(c["screen"]["t_screen_to_camera_mm"])
        denominators = vectors @ normal
        safe = abs(denominators) > 1e-12
        lambdas = np.full(len(a), np.nan)
        lambdas[safe] = ((t-origins[safe]) @ normal) / denominators[safe]
        points = origins + lambdas[:, None] * vectors
        xyz = camera_to_screen(points, c)
        pixel = mm_to_px(xyz[:, :2], c)
        errors = np.linalg.norm(pixel-a[:, :2], axis=1)
        residuals = abs(camera_to_screen(targets, c)[:, 2])
        valid = safe & (lambdas >= 0) & np.isfinite(errors)
        inconsistent = ~valid | (errors > tolerance_px) | (residuals > tolerance_mm)
        s = c["screen"]
        outside = ((a[:, 0] < 0) | (a[:, 0] > s["width_pixel"]) | (a[:, 1] < 0) | (a[:, 1] > s["height_pixel"]))
        full[annotation.stem] = {"rows": len(a), "reconstruction_px": describe(errors[valid]),
                                 "target_plane_residual_mm": describe(residuals),
                                 "inconsistent": int(inconsistent.sum()), "outside_display": int(outside.sum())}
        for i in np.flatnonzero(inconsistent | outside):
            warnings.append({"id": paths[i], "subject_id": annotation.stem, "gaze_screen_px": a[i, :2].tolist(),
                             "geometry_inconsistent": bool(inconsistent[i]), "outside_display": bool(outside[i]),
                             "reconstruction_error_px": float(errors[i]), "plane_residual_mm": float(residuals[i]),
                             "image_locally_available": (root / "raw/mpiifacegaze" / paths[i]).is_file(),
                             "action": "retained unchanged; no corrective flips, shifts or labels"})
    report["all_local_annotations"] = {"n": sum(r["rows"] for r in full.values()), "subjects": full,
                                         "inconsistent": sum(r["inconsistent"] for r in full.values()),
                                         "outside_display": sum(r["outside_display"] for r in full.values()),
                                         "scope": "all local labels; images need not be downloaded; no model evaluation on these additional rows"}
    write_jsonl(output / "annotation_warnings.jsonl", warnings)
    write_json(output / "geometry_consistency.json", report)
    return report
