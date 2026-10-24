import copy
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from usercamera.adapters import bbox, mobile_bounds
from usercamera.download import RemoteZipFile, extract_selected, extract_remote_selected, safe_member_path
from usercamera.evaluation import grouped_folds, grounding, matrix
from usercamera.geometry import angular_errors_deg, ray_screen_intersection, visual_angle_deg
from usercamera.io import write_jsonl
from usercamera.metrics import classification_metrics, paired_cluster_bootstrap
from usercamera.pilot import validate_pilot
from usercamera.synthetic import proxy_labels, synthesize


def test_visual_angle_units_and_monotonicity():
    # 100px at 254 PPI = 10mm; 500mm distance -> 1.14588 degrees.
    assert visual_angle_deg(100, 254, 500) == pytest.approx(1.145877395, abs=1e-8)
    assert visual_angle_deg(20, 326, 550) < visual_angle_deg(20, 326, 250)
    for bad in (0, -1, float("nan")):
        with pytest.raises(ValueError):
            visual_angle_deg(20, 326, bad)


def test_ray_and_angular_geometry():
    np.testing.assert_allclose(ray_screen_intersection([0, 0, 10], [0, 0, -1], [0, 0, 0], [0, 0, 1]), [0, 0, 0])
    for direction in ([1, 0, 0], [0, 0, 1]):
        with pytest.raises(ValueError):
            ray_screen_intersection([0, 0, 10], direction, [0, 0, 0], [0, 0, 1])
    np.testing.assert_allclose(angular_errors_deg([[1, 0, 0]], [[0, 1, 0]]), [90])


def test_bounds_actual_droidbot_and_funui_formats():
    assert mobile_bounds([[0, 5], [10, 20]]) == [0, 5, 10, 20]
    assert mobile_bounds("[0,5][10,20]") == [0, 5, 10, 20]
    assert bbox("[0,5,10,20]") == [0, 5, 10, 20]
    with pytest.raises(ValueError):
        bbox("[10,5,0,20]")


def test_zip_traversal_and_budget(tmp_path):
    for name in ("../evil", "/tmp/evil", "foo/../../evil", "foo\\evil"):
        with pytest.raises(ValueError):
            safe_member_path(tmp_path, name)
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr("ok.txt", "abc")
    data.seek(0)
    with zipfile.ZipFile(data) as z:
        with pytest.raises(ValueError):
            extract_selected(z, ["ok.txt"], tmp_path, max_uncompressed=2)
        assert not (tmp_path / "ok.txt").exists()


def test_range_ignored_is_rejected_without_read(monkeypatch):
    class Response:
        status = 200
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): raise AssertionError("Must not read a full archive response")
    monkeypatch.setattr("usercamera.download.request", lambda *args: Response())
    with pytest.raises(ValueError, match="byte range"):
        RemoteZipFile("https://example.test/a.zip", 1000).read(3)


def test_range_seek_across_blocks_and_cache(monkeypatch):
    content = bytes(range(100))
    calls = []
    class Response:
        status = 206
        def __init__(self, start, stop):
            self.start, self.stop = start, stop
            self.headers = {"Content-Range": f"bytes {start}-{stop}/100"}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return content[self.start:self.stop+1]
    def request(url, headers):
        start, stop = map(int, headers["Range"][6:].split("-"))
        calls.append((start, stop))
        return Response(start, stop)
    monkeypatch.setattr("usercamera.download.request", request)
    reader = RemoteZipFile("https://example.test/a.zip", 100, block_size=16)
    reader.seek(13)
    assert reader.read(20) == content[13:33]
    reader.seek(-5, 2)
    assert reader.read() == content[-5:]
    reader.seek(14)
    assert reader.read(2) == content[14:16]
    assert len(calls) == 5


@pytest.mark.parametrize("method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_concurrent_remote_entries_are_crc_verified(monkeypatch, tmp_path, method):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=method) as archive:
        archive.writestr("folder/hello.txt", "真实数据" * 100)
    content = data.getvalue()
    class Response:
        status = 206
        def __init__(self, start, stop):
            self.start, self.stop = start, stop
            self.headers = {"Content-Range": f"bytes {start}-{stop}/{len(content)}"}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return content[self.start:self.stop+1]
    def request(url, headers):
        return Response(*map(int, headers["Range"][6:].split("-")))
    monkeypatch.setattr("usercamera.download.request", request)
    remote = RemoteZipFile("https://example.test/data.zip", len(content))
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        result = extract_remote_selected(remote, archive, ["folder/hello.txt"], tmp_path)
    assert (tmp_path / "folder/hello.txt").read_text() == "真实数据" * 100
    assert len(result[0]["sha256"]) == 64


def test_mobile_system_activity_stays_in_collected_app_group(tmp_path):
    from usercamera.adapters import prepare_mobileviews
    folder = tmp_path / "raw/mobileviews/OneExample/states"
    folder.mkdir(parents=True)
    for i, app in enumerate(["app.main", "app.main", "android.system"]):
        Image.new("RGB", (100, 200), color=(i * 50, 0, 0)).save(folder / f"screen_{i}.jpg")
        state = {"foreground_activity": app + "/Activity", "views": [{"bounds": [[0, 0], [100, 100]], "clickable": True}]}
        (folder / f"state_{i}.json").write_text(json.dumps(state))
    screens, report = prepare_mobileviews(tmp_path)
    assert report["apps"] == 1
    assert {s["app_id"] for s in screens} == {"app.main"}


def test_public_action_csv_parses_quotes_and_keeps_discontinuities(tmp_path):
    from usercamera.adapters import prepare_mobileviews
    folder = tmp_path / "raw/mobileviews/OneExample"
    (folder / "states").mkdir(parents=True)
    for i in range(2):
        Image.new("RGB", (100, 200), color=(i * 50, 0, 0)).save(folder / "states" / f"screen_{i}.jpg")
        state = {"state_str": f"state{i}", "foreground_activity": "app.main/Activity", "views": []}
        (folder / "states" / f"state_{i}.json").write_text(json.dumps(state))
    (folder / "actions.csv").write_text('from_state,to_state,action\nstate0,state1,"touch <p bound_box=10,20,30,40>确认</p>"\nstate0,state1,kill_app\n')
    _, report = prepare_mobileviews(tmp_path)
    assert report["action_rows"] == 2
    assert report["action_audit"]["csv_sequence_discontinuities"] == 1
    from usercamera.io import read_jsonl
    actions = read_jsonl(tmp_path / "processed/mobileviews_actions.jsonl")
    assert actions[0]["action_bbox_px"] == [10, 20, 30, 40]
    assert actions[0]["from_screen_ids"] and actions[0]["to_screen_ids"]


def test_participant_app_split_has_no_variant_leakage():
    groups = np.repeat(["app1", "app2", "app3", "app4", "app5"], 12)
    tests = []
    for train, test in grouped_folds(groups):
        assert not set(groups[train]) & set(groups[test])
        tests.extend(test)
    assert sorted(tests) == list(range(60))
    with pytest.raises(ValueError):
        grouped_folds(["one", "one"])


def test_no_oracle_simulation_truth_in_model_features():
    row = {"screen": dict(glyph_height_px=20, contrast_ratio=5, element_count=6, target_x=.5, target_y=.5),
           "actions": dict(elapsed_s=5, clicks=1, backs=0),
           "user": dict(distance_estimate_mm=400, head_yaw_deg=0, head_pitch_deg=0),
           "simulation_truth": {"visual_angle_deg": 999, "distance_mm": 888}, "difficulty": "visual"}
    x = matrix([row], "SAU")
    row["simulation_truth"]["visual_angle_deg"] = -999
    row["difficulty"] = "none"
    np.testing.assert_equal(x, matrix([row], "SAU"))
    assert 888 not in x and 999 not in x


def test_proxy_labels_h3_includes_do_nothing():
    c = {"angle_threshold_deg": .3, "contrast_threshold": 3, "density_count_threshold": 24}
    assert proxy_labels(.5, 7, 6, c) == ("none", "none")
    assert proxy_labels(.1, 7, 6, c) == ("visual", "zoom")
    assert proxy_labels(.5, 2, 6, c) == ("visual", "hint")
    assert proxy_labels(.5, 7, 36, c) == ("navigation_proxy", "hint")


def test_metrics_use_true_none_denominator_and_handle_absent_classes():
    report = classification_metrics(["none", "none", "zoom"], [[.9, .1], [.1, .9], [.1, .9]], ["none", "zoom"])
    assert report["unnecessary_intervention_rate"] == .5
    assert report["macro_f1"] == pytest.approx(2 / 3)
    report = classification_metrics(["none", "none"], [[1, 0], [1, 0]], ["none", "zoom"])
    assert report["auroc_ovr"] is None
    report = paired_cluster_bootstrap(["none", "zoom"], ["none", "zoom"], ["none", "zoom"], ["a", "b"], ["none", "zoom"], repetitions=20)
    assert report["ci95"] == [0, 0]


def test_grounding_exclusions_and_missing_predictions_count_wrong(tmp_path):
    image = tmp_path / "im.png"
    Image.new("RGB", (100, 100)).save(image)
    base = dict(task="ui_grounding_cn", bbox_xyxy=[20, 20, 40, 40], bbox_valid=True,
                positive_grounding=True, question_contains_box=False, image_path=str(image))
    tasks = [dict(base, id="a"), dict(base, id="b"), dict(base, id="leak", question_contains_box=True),
             dict(base, id="negative", positive_grounding=False)]
    write_jsonl(tmp_path / "processed/funui_tasks.jsonl", tasks)
    predictions = tmp_path / "pred.jsonl"
    write_jsonl(predictions, [{"id": "a", "point_px": [30, 30]}])
    report = grounding(tmp_path, tmp_path / "reports", predictions)
    assert report["eligible"] == 2
    assert report["point_accuracy"] == .5
    assert report["missing_predictions_counted_wrong"] == 1


def pilot_row():
    return {"id": "p1:t1:0", "evidence_tier": "real_synchronized", "subject_id": "p1", "app_id": "app1",
            "trajectory_id": "t1", "camera_stream_id": "cam1", "screen_stream_id": "scr1",
            "clock": "common_monotonic_ms", "input_start_ms": 0, "input_end_ms": 5000, "label_time_ms": 5000,
            "camera_timestamp_ms": 4990, "screen_timestamp_ms": 4980, "action_cutoff_ms": 5000,
            "screen": dict(glyph_height_px=20, contrast_ratio=5, element_count=6, target_x=.5, target_y=.5),
            "actions": dict(elapsed_s=5, clicks=1, backs=0),
            "user": dict(distance_estimate_mm=400, head_yaw_deg=0, head_pitch_deg=0),
            "difficulty": "none", "intervention": "none", "difficulty_label_source": "self_report",
            "intervention_label_source": "independent_annotator"}


def test_pilot_rejects_unsynced_future_and_formula_labels():
    row = pilot_row()
    assert validate_pilot([row])["rows"] == 1
    for changes in ({"evidence_tier": "synthetic_proxy"}, {"screen_timestamp_ms": 3000},
                    {"action_cutoff_ms": 5001}, {"difficulty_label_source": "formula"},
                    {"input_end_ms": 5001}, {"camera_timestamp_ms": float("nan")}):
        with pytest.raises(ValueError):
            validate_pilot([dict(row, **changes)])


def test_synthesis_is_seeded_and_glyph_geometry_matches_render(tmp_path):
    from usercamera.cli import DEFAULT_CONFIG
    image = tmp_path / "original.png"
    Image.new("RGB", (300, 600)).save(image)
    screens = [{"id": "toy:s1", "source": "toy", "app_id": "app1", "image_path": str(image),
                "width": 300, "height": 600, "elements": [{"text": "医疗健康", "bounds": [10, 10, 100, 100]}]}]
    write_jsonl(tmp_path / "processed/screens.jsonl", screens)
    config = json.loads(DEFAULT_CONFIG.read_text())
    config["variants_per_screen"] = 3
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    synthesize(tmp_path, config_path)
    first = (tmp_path / "synthetic/scenarios.jsonl").read_bytes()
    synthesize(tmp_path, config_path)
    assert (tmp_path / "synthetic/scenarios.jsonl").read_bytes() == first
    from usercamera.io import read_jsonl
    for row in read_jsonl(tmp_path / "synthetic/scenarios.jsonl"):
        box = row["target_bbox_px"]
        assert box[3] - box[1] == row["screen"]["glyph_height_px"]
        assert row["evidence_tier"] == "synthetic_proxy"


def test_report_rejects_results_from_a_different_input(tmp_path):
    from usercamera.evaluation import make_report
    from usercamera.io import write_json
    output = tmp_path / "reports"
    write_json(output / "h1_public.json", {"input_sha256": "stale"})
    write_jsonl(tmp_path / "processed/mpii.jsonl", [{"id": "new-data"}])
    with pytest.raises(ValueError, match="Stale/mixed"):
        make_report(tmp_path, output)
