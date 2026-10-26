"""Host-side contracts. These tests do not execute Android hardware."""
import copy
import json
import shutil
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from jsonschema import Draft202012Validator
from usercamera.io import read_jsonl,write_json,write_jsonl,sha256
from usercamera.pilot_stimuli import build_protocol,validate_trial,render_trial,export_recorded_ui
from usercamera.pilot_session import make_mock_sessions,verify_folder,verify_session,read_trial,map_camera_frame,monotonic
from usercamera.pilot_features import extract_features,causal_window,camera_summary
from usercamera.pilot_temporal import split_windows,design_matrix,mismatched_user,fit_tabular,probability_metrics
from usercamera.mpii_expansion import verified_files,immutable_json


@pytest.fixture(scope='module')
def fixtures(tmp_path_factory):
    root=tmp_path_factory.mktemp('temporal_fixture')
    make_mock_sessions(root/'sessions',sessions=3,trials_per_session=3)
    for p in sorted((root/'sessions').glob('mock_s*')):extract_features(p,root/'reports',backend='mock',allow_mock=True)
    return root


@pytest.fixture
def mutable_session(fixtures,tmp_path):
    dest=tmp_path/'session';shutil.copytree(fixtures/'sessions/mock_s00',dest)
    (dest/'export_manifest.json').unlink()
    return dest


def search_trial(session):
    s=json.loads((session/'session.json').read_text())
    return session/'trials'/next(i for i in s['trial_ids'] if i.startswith('B_'))


def fixture_windows(fixtures):
    return [r for p in sorted((fixtures/'reports/features').rglob('windows.jsonl')) for r in read_jsonl(p) if r['mode']=='prefix_3s']


def test_stimuli_reproducibility_balanced_factors_targets_and_natural_text():
    a=build_protocol(42);assert a==build_protocol(42);assert a!=build_protocol(43)
    assert len([t for t in a['trials'] if t['task']=='fixation'])==50
    b=[t for t in a['trials'] if t['task']=='visual_search'];assert len(b)==48
    matrix=np.array([list(t['conditions']['factor_levels'].values()) for t in b])
    assert (matrix.sum(0)==24).all();np.testing.assert_allclose(np.corrcoef(matrix.T),np.eye(8),atol=1e-12)
    for t in a['trials']:
        assert validate_trial(t)
        if t['task']=='visual_search':
            assert t['correct_action_path']==[t['target_element_id']]
            assert len({e['text'] for e in t['elements']})==len(t['elements'])
            assert all(not any(c.isdigit() for c in e['text']) for e in t['elements'])
        assert 'difficulty' not in t


def test_rendered_ink_inside_clickable_boxes(tmp_path):
    t=next(t for t in build_protocol()['trials'] if t['task']=='visual_search' and t['conditions']['information_density']==1)
    path=tmp_path/'screen.png';render_trial(t,path)
    for e in json.loads(path.with_suffix('.json').read_text())['rendered_elements']:
        x0,y0,x1,y1=e['clickable_region_px']
        for a,b,c,d in e['ink_bounding_boxes_px']:assert x0<=a<c<=x1 and y0<=b<d<=y1
    broken=copy.deepcopy(t);broken['elements'][0]['bounding_box_px']=[-1,0,10,10]
    with pytest.raises(ValueError,match='outside'):validate_trial(broken)


def test_unknown_clock_never_silently_subtracted():
    f={'sensor_timestamp_ns':100,'arrival_elapsed_ns':1000,'mapped_timestamp_ns':900,'clock_source':'UNKNOWN'}
    assert map_camera_frame(f)==(None,None,'unresolved_clock')
    assert map_camera_frame(f,True)==(900,None,'estimated_unvalidated')
    f['clock_mapping']={'validated':True,'slope':1.,'offset_ns':800,'max_error_ns':1,
        'validation_method':'independent_capture_clock_pairs','anchors':[{'sensor_ns':n,'reference_capture_elapsed_ns':n+800} for n in [100,200,300]]}
    assert map_camera_frame(f)==(900,1.,'independent_mapping')
    f['clock_mapping']['anchors'][-1]['reference_capture_elapsed_ns']+=10
    with pytest.raises(ValueError,match='exceeds'):map_camera_frame(f)


def test_realtime_identity_and_nonmonotonic_timestamps():
    r={'sensor_timestamp_ns':100,'arrival_elapsed_ns':130,'mapped_timestamp_ns':100,'clock_source':'REALTIME'}
    assert map_camera_frame(r)==(100,0,'shared_clock');r['mapped_timestamp_ns']=130
    with pytest.raises(ValueError,match='REALTIME'):map_camera_frame(r)
    for rows in [[{'t':2},{'t':1}],[{'t':float('nan')}]]:
        with pytest.raises(ValueError):monotonic(rows,'t')


def test_mock_files_and_windows_validate_machine_schema(fixtures):
    schema=json.loads(Path('mobile_pilot/schema/session.schema.json').read_text())
    def check(kind,data):Draft202012Validator({**schema,'$ref':'#/$defs/'+kind}).validate(data)
    folder=fixtures/'sessions/mock_s00';s=json.loads((folder/'session.json').read_text());check('session',s)
    for trial_id in s['trial_ids']:
        t=read_trial(folder/'trials'/trial_id);check('trial_meta',t['meta']);check('feedback',t['feedback'])
        for key,kind in [('camera','camera_frame'),('ui','ui_state'),('touch','touch_event')]:
            for row in t[key]:check(kind,row)
    for row in read_jsonl(fixtures/'reports/features/mock_s00/windows.jsonl'):check('feature_window',row)


def test_mock_guard_and_session_ownership(mutable_session):
    with pytest.raises(ValueError,match='allow-mock'):verify_folder(mutable_session)
    assert verify_folder(mutable_session,True)['evidence_tier']=='mock'
    d=search_trial(mutable_session);m=json.loads((d/'trial_meta.json').read_text());m['session_id']='foreign';write_json(d/'trial_meta.json',m)
    with pytest.raises(ValueError,match='ownership'):verify_folder(mutable_session,True)


def test_difficulty_provenance_rejects_condition_formulas(mutable_session):
    d=search_trial(mutable_session);f=json.loads((d/'feedback.json').read_text());f['label_source']='font_distance_formula';write_json(d/'feedback.json',f)
    with pytest.raises(ValueError,match='provenance'):verify_folder(mutable_session,True)
    f.update(label_source='mock_self_report_fixture',difficulty_rating=True);write_json(d/'feedback.json',f)
    with pytest.raises(ValueError,match='integer1..5'):verify_folder(mutable_session,True)


def test_missing_camera_is_recorded_not_fabricated(mutable_session):
    s=json.loads((mutable_session/'session.json').read_text())
    for trial_id in s['trial_ids']:write_jsonl(mutable_session/'trials'/trial_id/'camera_frames.jsonl',[])
    q=verify_folder(mutable_session,True)
    assert q['missing_camera_trial_fraction']==1 and not q['clock_alignment_usable']


def test_corrupt_frame_decode_even_with_updated_hash(mutable_session):
    d=search_trial(mutable_session);frames=read_jsonl(d/'camera_frames.jsonl');p=d/frames[0]['path'];p.write_bytes(b'not a JPEG')
    frames[0]['sha256']=sha256(p);write_jsonl(d/'camera_frames.jsonl',frames)
    with pytest.raises(OSError):verify_folder(mutable_session,True)
    p=d/'front_camera.mp4';p.write_bytes(b'not a valid video container')
    frames[0].update(path='front_camera.mp4',sha256=sha256(p));write_jsonl(d/'camera_frames.jsonl',frames)
    with pytest.raises(ValueError,match='MP4 import not implemented'):verify_folder(mutable_session,True)


def test_missing_files_and_duplicate_capture_timestamps(mutable_session):
    d=search_trial(mutable_session);f=read_jsonl(d/'camera_frames.jsonl');f[1]['sensor_timestamp_ns']=f[0]['sensor_timestamp_ns'];write_jsonl(d/'camera_frames.jsonl',f)
    with pytest.raises(ValueError,match='Nonmonotonic'):verify_folder(mutable_session,True)
    f[1]['sensor_timestamp_ns']+=200000000;write_jsonl(d/'camera_frames.jsonl',f);(d/f[0]['path']).unlink()
    with pytest.raises(ValueError,match='missing/corrupt'):verify_folder(mutable_session,True)


def test_zip_export_import_and_path_validation(fixtures,tmp_path):
    source=fixtures/'sessions/mock_s00';archive=tmp_path/'session.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in source.rglob('*'):
            if p.is_file():z.write(p,str(p.relative_to(source)))
    assert len(verify_session(archive,tmp_path/'reports',True)['trials'])==4
    bad=tmp_path/'bad.zip'
    with zipfile.ZipFile(bad,'w') as z:z.writestr('../escape.txt','bad')
    with pytest.raises(ValueError,match='escapes'):verify_session(bad,tmp_path/'reports',True)


def test_touch_clock_conversion_is_verified(mutable_session):
    d=search_trial(mutable_session);events=read_jsonl(d/'touch_events.jsonl')
    events[0].update(raw_uptime_ms=1,event_clock_offset_ns=0,mapping_uncertainty_ns=1000);write_jsonl(d/'touch_events.jsonl',events)
    with pytest.raises(ValueError,match='Touch clock'):verify_folder(mutable_session,True)


def test_future_frames_actions_outcomes_and_feedback_cannot_affect_prefix(fixtures):
    d=search_trial(fixtures/'sessions/mock_s00');t=read_trial(d);frames=read_jsonl(d/'mock_camera_observations.jsonl')
    for f in frames:f['available_ns']=f['timestamp_ns']+12000000
    start=t['meta']['onset_ns'];cutoff=start+1000000000;a=causal_window(t,frames,cutoff)
    t['meta']['outcome']={'success':False,'misclicks':99999};t['feedback']['difficulty_rating']=5
    t['touch'].append({'timestamp_ns':cutoff+1000000,'action':'up','correct_target_hit':False})
    late=copy.deepcopy(t['ui'][0]);late['timestamp_ns']=cutoff+1;late['elements'][0]['font_glyph_height_px']=999;t['ui'].append(late)
    for f in frames:
        if f['timestamp_ns']>cutoff:f['face_scale']=1e-9;f['yaw_deg']=160
    assert a==causal_window(t,frames,cutoff)
    assert camera_summary([{'timestamp_ns':cutoff-1,'available_ns':cutoff+1,'face_present':True}],start,cutoff)['camera_observed']==0


def test_temporal_changes_respect_elapsed_time():
    f=[{'timestamp_ns':i*100000000,'available_ns':i*100000000,'face_present':True,'face_scale':.2+.02*i,'yaw_deg':10*i,'pitch_deg':0,'roll_deg':0} for i in range(3)]
    s=camera_summary(f,0,200000000)
    assert s['relative_inverse_scale_change']==pytest.approx(.2/.24-1)
    assert s['angular_velocity_deg_s']==pytest.approx(100) and s['head_rotation_magnitude_deg']==pytest.approx(20)


def test_session_participant_and_exact_template_leakage_guards(fixtures):
    rows=fixture_windows(fixtures);key,folds,status=split_windows(rows);assert key=='session_id' and len(folds)==3
    for train,val,test in folds:
        for field in [key,'template_id']:
            a,b,c=[{rows[i][field] for i in ix} for ix in [train,val,test]]
            assert not(a&b or a&c or b&c)
    cloned=copy.deepcopy(rows)
    for r in cloned:r['participant_id']=r['session_id']
    assert split_windows(cloned)[0]=='participant_id'
    for r in cloned:r['template_id']='same_rendered_template'
    assert split_windows(cloned)[2]['status']=='insufficient_after_template_purge'


def test_multiple_prefixes_of_one_trial_cannot_cross_splits(fixtures):
    rows=fixture_windows(fixtures);other=copy.deepcopy(rows[0]);other['id']+='second';other['mode']='prefix_1s'
    with pytest.raises(ValueError,match='multiple prefixes'):split_windows(rows+[other])
    assert split_windows(rows[:3])[2]['status']=='insufficient_groups'


def test_mismatched_user_is_past_and_within_partition(fixtures):
    rows=fixture_windows(fixtures);indices=np.arange(len(rows));donors=mismatched_user(rows,indices)
    for i,donor in donors.items():
        if donor is not None:
            assert donor in indices and rows[i]['session_id']==rows[donor]['session_id']
            assert rows[donor]['input_end_ns']<=rows[i]['input_start_ns']
    a,sequence,trace=design_matrix(rows,indices,'M5');assert len(a)==len(rows) and sequence.shape[1]==6


def test_train_only_imputation_and_independent_test_rows():
    rng=np.random.default_rng(3);a=rng.normal(size=(20,6));b=rng.normal(size=(6,6));c=rng.normal(size=(3,6))
    y=np.arange(20)%2;yv=np.arange(6)%2;a[:,0]=np.nan
    p,_=fit_tabular(a,y,b,yv,c,'logistic');c[-1]=1e9
    pp,_=fit_tabular(a,y,b,yv,c,'logistic');assert p[0]==pytest.approx(pp[0])
    m=probability_metrics([0,0,1,1],[.1,.2,.8,.9]);assert m['AUROC']==1 and m['macro_f1']==1 and m['brier_score']<.05


def test_trial_labels_not_copied_to_frame_features(fixtures):
    frames=read_jsonl(fixtures/'reports/features/mock_s00/camera_features.jsonl')
    assert all('difficulty' not in r and 'difficulty_rating' not in r for r in frames)
    for r in fixture_windows(fixtures):assert r['label_resolution']=='trial_only' and r['input_end_ns']<r['label_time_ns']


def test_model_frame_failure_is_retained_as_missing_not_silently_dropped(fixtures,tmp_path,monkeypatch):
    class FailedBackend:
        def __init__(self,*args):pass
        def extract(self,*args):raise RuntimeError('fixture inference failure')
        def close(self):pass
    monkeypatch.setattr('usercamera.pilot_features.FaceLandmarkerBackend',FailedBackend)
    r=extract_features(fixtures/'sessions/mock_s00',tmp_path/'failed',backend='mediapipe',allow_mock=True)
    assert r['feature_failure_frames']==r['frames'] and r['frames']>0
    windows=read_jsonl(tmp_path/'failed/features/mock_s00/windows.jsonl')
    assert windows and all(w['user']['camera_feature_missing_fraction']==1 for w in windows)


def test_mpii_manifest_hash_and_immutable_view_preservation(tmp_path):
    image=tmp_path/'Data/p00/day01/one.jpg';image.parent.mkdir(parents=True);Image.new('RGB',(10,10),'gray').save(image)
    record={'member':str(image.relative_to(tmp_path)),'bytes':image.stat().st_size,'sha256':sha256(image)}
    before=image.read_bytes();assert verified_files(tmp_path,[record])=={record['member']};assert image.read_bytes()==before
    with pytest.raises(ValueError,match='hash/size'):verified_files(tmp_path,[{**record,'sha256':'0'*64}])
    with pytest.raises(ValueError,match='Escaping'):verified_files(tmp_path,[{**record,'member':'../escape.jpg'}])
    manifest=tmp_path/'view.json';immutable_json(manifest,{'n':1});saved=manifest.read_bytes()
    with pytest.raises(ValueError,match='Immutable'):immutable_json(manifest,{'n':2})
    assert manifest.read_bytes()==saved


def test_exact_app_screenshot_export(fixtures,tmp_path):
    r=export_recorded_ui(fixtures/'sessions/mock_s00',tmp_path/'exports',True);assert r['exported_stimuli']==4
    for path in r['files']:
        p=Path(path);assert json.loads(p.with_suffix('.json').read_text())['screenshot_sha256']==sha256(p)


def test_native_project_no_network_upload_permission():
    manifest=ET.parse('mobile_pilot/app/src/main/AndroidManifest.xml').getroot();android='{http://schemas.android.com/apk/res/android}'
    assert {e.attrib[android+'name'] for e in manifest.findall('uses-permission')}=={'android.permission.CAMERA'}
    for p in ['settings.gradle.kts','build.gradle.kts','app/build.gradle.kts','gradlew','gradle/wrapper/gradle-wrapper.jar']:assert (Path('mobile_pilot')/p).is_file()
    assert 'distributionSha256Sum=' in Path('mobile_pilot/gradle/wrapper/gradle-wrapper.properties').read_text()


def test_new_cli_dispatch(monkeypatch):
    from usercamera.cli import main
    calls=[];monkeypatch.setattr('usercamera.mpii_expansion.integrate_expansion',lambda *a:calls.append(a) or {})
    assert main(['mpii-integrate-expansion','--output','scratch'])==0
    assert calls[0]==('data','data/expansions/mpii_v1','scratch')
