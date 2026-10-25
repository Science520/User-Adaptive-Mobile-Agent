import copy
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from scipy.io import savemat
from scipy.spatial.transform import Rotation

from usercamera.adapters import prepare_mpii
from usercamera.camera_screen_geometry import (
    camera_to_screen, convention_diagnostics, intersect_gaze, load_calibration,
    mm_to_px, px_to_mm, screen_to_camera, validate_geometry,
)
from usercamera.io import read_jsonl, write_json, write_jsonl
from usercamera.mpii_models import build_feature_sets, crop_boxes, fit_predict_fold, metadata_features, prediction_errors


def calibration_files(folder, rotation_field="rvects"):
    folder.mkdir(parents=True, exist_ok=True)
    rvec = np.array([.1, 3.05, -.03])
    savemat(folder / "Camera.mat", {"cameraMatrix": [[700,0,320],[0,710,240],[0,0,1]],
                                  "distCoeffs": [[.01, -.02, 0, 0, 0]], "retval": [[.3]],
                                  "rvecs": [[9, 8, 7]], "tvecs": [[100, 200, 300]]})
    savemat(folder / "monitorPose.mat", {rotation_field: rvec.reshape(3,1), "tvecs": [[110], [5], [-25]]})
    savemat(folder / "screenSize.mat", {"width_mm": [[300]], "height_mm": [[200]],
                                       "width_pixel": [[1920]], "height_pixel": [[1200]]})
    return rvec


def make_sample(tmp_path):
    base = tmp_path / "raw/mpiifacegaze"
    subject = base / "Data/p00"
    rvec = calibration_files(subject / "Calibration")
    c = load_calibration(subject / "Calibration", "p00")
    origin = screen_to_camera([150, 100, -500], c)
    pixel = [400, 300]
    xy = px_to_mm(pixel, c)
    target = screen_to_camera([*xy, 0], c)
    points = [[200, 160], [230, 160], [300, 160], [330, 160], [230, 270], [310, 270]]
    image = subject / "day01/0001.jpg"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (640,480), "gray").save(image)
    values = [*pixel, *np.asarray(points).reshape(-1), .1, .2, .3, *origin, *origin, *target]
    line = "day01/0001.jpg " + " ".join(str(x) for x in values) + " left\n"
    (subject / "p00.txt").write_text(line)
    write_json(base / "manifest.json", {"selected_images": ["Data/p00/day01/0001.jpg"]})
    prepare_mpii(tmp_path)
    return read_jsonl(tmp_path / "processed/mpii.jsonl")[0]


@pytest.mark.parametrize("field", ["rvects", "rvecs"])
def test_monitor_rotation_is_not_camera_board_pose(tmp_path, field):
    rvec = calibration_files(tmp_path, field)
    c = load_calibration(tmp_path, "p00")
    np.testing.assert_allclose(c["screen"]["R_screen_to_camera"], Rotation.from_rotvec(rvec).as_matrix())
    assert c["screen"]["rotation_field_in_mat"] == field
    assert c["camera"]["board_pose_count"] == 1
    assert c["units"]["length"] == "mm"
    assert set(c["source_files"]) == {"Camera.mat", "monitorPose.mat", "screenSize.mat"}


def test_nontrivial_extrinsics_and_mm_pixel_roundtrip(tmp_path):
    calibration_files(tmp_path)
    c = load_calibration(tmp_path, "p00")
    points = np.array([[0,0,0], [150,100,0], [300,200,0], [25,30,-500]])
    np.testing.assert_allclose(camera_to_screen(screen_to_camera(points,c),c), points, atol=1e-12)
    pixels = mm_to_px([[0,0], [150,100], [300,200]], c)
    np.testing.assert_allclose(pixels, [[0,0], [960,600], [1920,1200]])
    np.testing.assert_allclose(px_to_mm(pixels,c), points[:3,:2])
    assert not np.allclose(pixels[-1], [1919,1199])


def test_ray_reconstruction_and_source_schema(tmp_path):
    row = make_sample(tmp_path)
    c = row["calibration"]
    direction = np.asarray(row["gaze_target_mm"]) - row["face_center_mm"]
    point = intersect_gaze(row["face_center_mm"], direction, c)
    np.testing.assert_allclose(point["screen_xy_px"], row["gaze_screen_px"], atol=1e-10)
    report = validate_geometry(tmp_path, tmp_path / "reports")
    assert report["is_gaze_model_accuracy"] is False
    assert report["inconsistent_ids"] == []
    assert report["all_local_annotations"]["n"] == 1
    assert row["schema_version"] == "mpii-sample-v2"
    for field in ("landmarks_2d", "head_rvec", "face_center_mm", "gaze_target_mm", "gaze_screen_px", "image_path"):
        assert field in row


def test_inconsistent_label_is_flagged_not_corrected(tmp_path):
    row = make_sample(tmp_path)
    row["gaze_screen_px"][0] += 10
    write_jsonl(tmp_path / "processed/mpii.jsonl", [row])
    report = validate_geometry(tmp_path, tmp_path / "reports")
    assert report["inconsistent_ids"] == [row["id"]]
    assert read_jsonl(tmp_path / "processed/mpii.jsonl")[0]["gaze_screen_px"] == row["gaze_screen_px"]
    errors = read_jsonl(tmp_path / "reports/geometry_errors.jsonl")
    assert errors[0]["reconstruction_error_px"] == pytest.approx(10)
    assert errors[0]["diagnostics_px"]["wrong_one_based_offset"] > 0


def test_wrong_conventions_diagnosed_and_outside_labels_retained(tmp_path):
    row = make_sample(tmp_path)
    d = convention_diagnostics(row)
    assert d["fixed_documented_convention"] < 1e-9
    assert d["wrong_center_origin"] > 100
    assert d["wrong_mm_as_cm_scale"] > 100
    c = row["calibration"]
    # A point outside the display can still satisfy every rigid-geometry equation.
    row["gaze_screen_px"] = [2100, 400]
    row["gaze_target_mm"] = screen_to_camera([*px_to_mm(row["gaze_screen_px"],c),0],c).tolist()
    write_jsonl(tmp_path / "processed/mpii.jsonl", [row])
    r = validate_geometry(tmp_path,tmp_path / "reports")
    assert r["inconsistent_ids"] == []
    assert r["subjects"]["p00"]["outside_display"] == 1


def test_parallel_behind_nonfinite_and_zero_rays_fail(tmp_path):
    row = make_sample(tmp_path)
    c = row["calibration"]
    R = np.asarray(c["screen"]["R_screen_to_camera"])
    for direction in (R[:,0], -np.asarray(row["gaze_direction"]), [0,0,0], [0,0,float("nan")]):
        with pytest.raises(ValueError):
            intersect_gaze(row["face_center_mm"],direction,c)


def test_gaze_targets_cannot_change_features_or_crop(tmp_path):
    row = make_sample(tmp_path)
    poisoned = copy.deepcopy(row)
    poisoned.update(gaze_target_mm=[1e9]*3, gaze_direction=[-999]*3, gaze_screen_px=[9e9]*2, face_center_mm=[1e6]*3)
    for key, value in metadata_features(row).items():
        np.testing.assert_equal(metadata_features(poisoned)[key],value)
    assert crop_boxes(poisoned) == crop_boxes(row)
    appearance = np.random.default_rng(42).normal(size=(1,1536))
    first, second = build_feature_sets([row],appearance), build_feature_sets([poisoned],appearance)
    for name in first:
        np.testing.assert_equal(first[name][0],second[name][0])


def test_train_only_scaling_pca_and_no_test_label_leakage():
    rng = np.random.default_rng(42)
    x, y = rng.normal(size=(12,48)), rng.normal(size=(12,8))
    train,test = np.arange(8),np.arange(8,12)
    first = fit_predict_fold(x,y,train,test,32)
    y[test] = 1e12
    x[-1] = 1e8
    second = fit_predict_fold(x,y,train,test,32)
    np.testing.assert_allclose(first[0],second[0],atol=1e-12)


def test_screen_head_does_not_use_target_face_center_and_ray_failures_count(tmp_path):
    row = make_sample(tmp_path)
    prediction = np.array([[*row["gaze_direction"], .5, .5, 0,0,.5]])
    first, samples = prediction_errors(prediction,[row])
    row["face_center_mm"] = [100000,200000,-300000]
    second, _ = prediction_errors(prediction,[row])
    assert first["screen_direct_error_mm"] == second["screen_direct_error_mm"]
    prediction[0,:3] = 0
    m, s = prediction_errors(prediction,[row])
    assert m["predicted_origin_ray"]["invalid_count"] == 1
    assert m["annotated_origin_ray"]["invalid_count"] == 1
    assert s[0]["angular_error_deg"] == 180
    assert s[0]["degenerate_predicted_direction"]


def test_crop_boxes_and_bad_landmarks(tmp_path):
    row = make_sample(tmp_path)
    boxes = crop_boxes(row)
    assert len(boxes) == 3
    assert boxes[1][0] < boxes[2][0]
    for box in boxes:
        assert 0 <= box[0] < box[2] <= row["image_width"]
        assert 0 <= box[1] < box[3] <= row["image_height"]
    row["landmarks_2d"] = [[0,0]]*6
    with pytest.raises(ValueError,match="Degenerate"):
        crop_boxes(row)


def test_missing_calibration_does_not_silently_default(tmp_path):
    calibration_files(tmp_path)
    (tmp_path / "monitorPose.mat").unlink()
    with pytest.raises((OSError,FileNotFoundError)):
        load_calibration(tmp_path,"p00")


def test_cli_grounding_option_did_not_move_to_mpii(monkeypatch):
    from usercamera.cli import main
    called = []
    monkeypatch.setattr("usercamera.cli.grounding",lambda *args: called.append(args) or {})
    assert main(["grounding","--predictions","predictions.jsonl"]) == 0
    assert called[0][-1] == "predictions.jsonl"


def test_selected_bad_eye_flag_is_not_accepted(tmp_path):
    make_sample(tmp_path)
    path = tmp_path / "raw/mpiifacegaze/Data/p00/p00.txt"
    path.write_text(path.read_text().replace(" left", " unknown"))
    audit = prepare_mpii(tmp_path)
    assert audit["rows"] == 0
    assert len(audit["invalid"]) == 1
    assert audit["full_annotation_format_errors"] == 1


def test_original_manifest_integrity_prevents_silent_corruption(tmp_path):
    make_sample(tmp_path)
    path = tmp_path / "raw/mpiifacegaze/manifest.json"
    manifest = json.loads(path.read_text())
    manifest["files"] = [{"member": "Data/p00/day01/0001.jpg", "sha256": "wrong-digest"}]
    write_json(path, manifest)
    with pytest.raises(ValueError, match="Original MPII files changed"):
        prepare_mpii(tmp_path)
