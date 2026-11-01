import json
from collections import Counter
from fractions import Fraction
from pathlib import Path
import pytest
from usercamera.pilot_design_v3 import build_protocol_v3,WILLIAMS
from usercamera.pilot_v3_audit import fps_stats
from usercamera.pilot_v3_temporal import eligible_live,recent_summary

@pytest.fixture(scope='module')
def design():return build_protocol_v3()[0]


def test_full_design_unique_and_balanced(design):
    for trials in design['plans'].values():
        assert len(trials)==len({t['target_id'] for t in trials})==len({t['target_text'] for t in trials})==24
        assert set(Counter(t['condition_id'] for t in trials).values())=={6}
        assert set(Counter(t['target_position']['zone_2x2'] for t in trials).values())=={6}
        assert set(Counter((t['condition_id'],t['target_position']['zone_2x2']) for t in trials).values())<={1,2}


def test_quick_design_balances_conditions_and_space(design):
    for trials in design['quick_plans'].values():
        assert len(trials)==len({t['target_id'] for t in trials})==8
        assert set(Counter(t['condition_id'] for t in trials).values())=={2}
        assert set(Counter(t['target_position']['zone_2x2'] for t in trials).values())=={2}


def test_future_targets_never_appear_as_distractors(design):
    for trials in design['plans'].values():
        targets={t['target_text'] for t in trials}
        for t in trials:
            assert not (set(t['distractor_pool']) & targets)


def test_each_target_crosses_every_condition_and_zone(design):
    ids={t['target_id'] for t in design['plans']['0']}
    for target_id in ids:
        pairs=[(t['condition_id'],t['target_position']['zone_2x2']) for ts in design['plans'].values() for t in ts if t['target_id']==target_id]
        assert len(pairs)==len(set(pairs))==16


def test_font_is_only_element_manipulation_for_matched_target(design):
    a=next(t for t in design['plans']['0'] if t['condition_id']=='easy_low')
    b=next(t for t in design['plans']['1'] if t['target_id']==a['target_id'])
    assert b['condition_id']=='hard_low'
    assert len(a['elements'])==len(b['elements'])==6
    for x,y in zip(a['elements'],b['elements']):
        assert {k for k in x if x[k]!=y[k]}=={'font_glyph_height_px'}


def test_high_load_adds_distractors_keeps_core_choices(design):
    a=next(t for t in design['plans']['0'] if t['condition_id']=='easy_low')
    b=next(t for t in design['plans']['2'] if t['target_id']==a['target_id'])
    assert b['condition_id']=='easy_high' and len(b['elements'])==24
    lookup={e['element_id']:e for e in b['elements']}
    assert all(e==lookup[e['element_id']] for e in a['elements'])


def test_williams_first_order_carryover():
    pairs=[(a,b) for order in WILLIAMS for a,b in zip(order,order[1:])]
    assert len(pairs)==len(set(pairs))==12


def test_family_is_not_actual_difficulty_label(design):
    for t in design['plans']['0']:
        assert t['difficulty_manipulation']['actual_human_difficulty_label'] is False
        assert t['task'] in ['readability','visual_search','mixed']
        assert len(t['elements']) in [6,24]


def test_fps_does_not_bridge_disjoint_periods():
    r=fps_stats([0,33333,66666,10_000_000,10_033_333],[0,1,3,4])
    assert r['gaps_over_75ms']==0
    assert abs(r['instant_fps']['median']-30)<.01
    assert abs(r['within_period_effective_fps']-30)<.01


def test_fps_counts_duplicate_and_gap():
    r=fps_stats([0,33333,33333,200000]);assert r['duplicates']==1 and r['gaps_over_75ms']==1


def test_rational_pts_conversion_regression():
    # This source sample produced a 1us false mismatch when multiplied by float 1e6.
    pts=129870400;tb=Fraction(1,1000000)
    assert int(pts*tb*1000000)==pts


def test_recent_observations_require_capture_and_availability_before_cutoff():
    rows=[{'timestamp_ns':10,'available_ns':12},{'timestamp_ns':13,'available_ns':20},{'timestamp_ns':20,'available_ns':20}]
    assert eligible_live(rows,0,20)==rows[:1]


def test_relative_scale_does_not_become_metric_distance():
    r=recent_summary([{'timestamp_ns':0,'face_present':True,'face_scale':.5},{'timestamp_ns':100000000,'face_present':True,'face_scale':.25}])
    assert r['relative_scale_change']==-.5 and not any('mm' in k or 'gaze' in k for k in r)


def test_missing_faces_preserved_as_mask():
    r=recent_summary([{'timestamp_ns':1,'face_present':False}]);assert r['missing'] and r['face_fraction']==0 and r['yaw_proxy_deg_mean'] is None


def test_training_cache_refuses_overwrite(tmp_path):
    from usercamera.pilot_v3_cache import cache_training_inputs
    (tmp_path/'training_cache.npz').write_bytes(b'preserved')
    with pytest.raises(ValueError,match='exists'):cache_training_inputs(private=tmp_path)
    assert (tmp_path/'training_cache.npz').read_bytes()==b'preserved'


def test_v3_cli_dispatch_is_separate_from_old_protocol(monkeypatch,tmp_path):
    from usercamera.cli import main
    seen=[]
    monkeypatch.setattr('usercamera.pilot_design_v3.generate_design',lambda *args:seen.append(args) or {})
    assert main(['pilot-v3-design','--output',str(tmp_path),'--asset',str(tmp_path/'protocol.json'),'--seed','77'])==0
    assert seen[0][2]==77


def test_helpfulness_does_not_use_zero_as_missing():
    import jsonschema
    schema=json.loads(Path('mobile_pilot/schema/temporal-pilot-v3.schema.json').read_text())['$defs']['feedback_v3_1']
    value={'status':'provided','difficulty_rating':4,'label_source':'self_report','label_schema_version':'self-report-v3.1','helpfulness_status':'unable_to_rate','helpfulness_rating':None}
    jsonschema.validate(value,schema)
    value['helpfulness_rating']=0
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(value,schema)
    value.update(helpfulness_status='provided',helpfulness_rating=3);jsonschema.validate(value,schema)


def test_evaluation_guard_reports_selection_and_sync_limits():
    from usercamera.pilot_v3_evaluation import readiness
    rows=[{'participant_id':'p','session_id':'s','protocol_version':'v3','label_schema_version':'v3.1','evidence_tier':'real_device_recording','clock_alignment_usable':False,'label':1}]
    q=readiness(rows,'label')
    assert 'unverified_video_UI_touch_alignment' in q['blockers']
    assert 'target_has_one_or_zero_classes_after_prefix_selection' in q['blockers']
    assert 'fewer_than_three_independent_train_validation_test_groups' in q['blockers']


def test_evaluation_guard_rejects_mixed_task_protocols():
    from usercamera.pilot_v3_evaluation import readiness
    a={'participant_id':'p1','session_id':'s1','protocol_version':'v2','evidence_tier':'real_device_recording','clock_alignment_usable':True,'label':0}
    b={**a,'participant_id':'p2','protocol_version':'v3','label':1}
    assert 'mixed_task_or_label_protocols' in readiness([a,b],'label')['blockers']
