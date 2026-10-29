import json
from copy import deepcopy
from pathlib import Path
import pytest
from usercamera.io import write_json,write_jsonl,sha256
from usercamera.pilot_video import estimate_elapsed,touch_coordinates_valid,verify_manifest,video_frames,replay,inspect_folder
from usercamera.pilot_inputs_v2 import causal_prefix,evaluate_v2
from usercamera.pilot_design_v2 import build_protocol_v2


def test_pause_resume_piecewise_mapping():
    anchors=[{'recorded_duration_ns':0,'timestamp_ns':10_000_000_000},{'recorded_duration_ns':2_000_000_000,'timestamp_ns':20_000_000_000}]
    assert estimate_elapsed(500_000,0,anchors)==10_500_000_000
    assert estimate_elapsed(2_500_000,0,anchors)==20_500_000_000
    assert estimate_elapsed(0,0,[]) is None


@pytest.mark.parametrize('seconds',[1,2,3,5])
def test_fixed_prefix_strict_help_boundary(seconds):
    start=10_000_000_000;meta={'onset_ns':start,'offset_ns':start+10_000_000_000}
    touch=[{'action':'help_request','timestamp_ns':start+seconds*1_000_000_000}]
    value,reason=causal_prefix(meta,touch,seconds)
    assert value is None and 'pre-help' in reason


def test_no_future_or_help_as_feature():
    meta={'onset_ns':0,'offset_ns':10_000_000_000}
    events=[{'action':'up','timestamp_ns':200_000_000},{'action':'up','timestamp_ns':1_000_000_000},{'action':'help_request','timestamp_ns':3_000_000_000}]
    value,error=causal_prefix(meta,events,1)
    assert error is None and len(value['actions'])==1 and value['future_help']==1
    assert value['label_time_ns']>value['cutoff_ns']


def test_coordinates_origin_and_wrong_axis():
    row={'action':'move','x_px':5.5,'y_px':9,'screen_x_px':105.5,'screen_y_px':209,'view_origin_screen_px':[100,200]}
    assert touch_coordinates_valid(row)
    row['screen_y_px']=9
    assert not touch_coordinates_valid(row)
    assert not touch_coordinates_valid({'action':'up'})


def test_hash_and_unmanifested_corruption(tmp_path):
    p=tmp_path/'front_camera.mp4';p.write_bytes(b'abc')
    write_json(tmp_path/'export_manifest.json',{'files':[{'path':p.name,'bytes':3,'sha256':sha256(p)}]})
    assert verify_manifest(tmp_path)==1
    p.write_bytes(b'abd')
    with pytest.raises(ValueError,match='Corrupt'):verify_manifest(tmp_path)


def test_manifest_path_escape(tmp_path):
    write_json(tmp_path/'export_manifest.json',{'files':[{'path':'../private','bytes':0,'sha256':'bad'}]})
    with pytest.raises(ValueError,match='escapes'):verify_manifest(tmp_path)


def test_matched_pairs_change_only_one_factor():
    design=build_protocol_v2();pairs={}
    for t in design['trials']:
        if t['task']=='visual_search':pairs.setdefault(t['pair_id'],[]).append(t)
    assert len(pairs)==16
    for pair,rows in pairs.items():
        original=rows[0]
        for other in rows[1:]:
            assert original['instruction']==other['instruction']
            assert len(original['elements'])==len(other['elements'])==24
            assert [e['text'] for e in original['elements']]==[e['text'] for e in other['elements']]
            for a,b in zip(original['elements'],other['elements']):
                changed={k for k in a if a[k]!=b[k]}
                allowed={'font_glyph_height_px'} if pair.endswith('font') else {'bounding_box_px','clickable_region_px'} if pair.endswith('position') else {'foreground_gray','visual_contrast'} if pair.endswith('contrast') else set()
                assert changed<=allowed


def test_video_real_decode_and_pts(tmp_path):
    av=pytest.importorskip('av');import numpy as np
    path=tmp_path/'technical_fixture.mp4'
    with av.open(str(path),'w') as container:
        stream=container.add_stream('libx264',rate=24);stream.width=64;stream.height=48;stream.pix_fmt='yuv420p'
        for i in range(24):
            frame=av.VideoFrame.from_ndarray(np.full((48,64,3),i*8,dtype=np.uint8),format='rgb24')
            for packet in stream.encode(frame):container.mux(packet)
        for packet in stream.encode():container.mux(packet)
    frames=list(video_frames(path))
    assert len(frames)==24 and frames[0]['codec']=='h264'
    assert frames[-1]['pts_us']>frames[0]['pts_us'] and frames[0]['audio_tracks']==0
    path.write_bytes(b'broken')
    with pytest.raises((ValueError,OSError)):list(video_frames(path))


def test_unverified_fusion_never_runs(tmp_path):
    root=tmp_path/'inputs';root.mkdir()
    write_jsonl(root/'windows_v2.jsonl',[{'participant_id':'p1','clock_alignment_usable':False}])
    result=evaluate_v2(root,tmp_path/'out')
    assert result['status']=='blocked_unverified_sync' and not result['supports_cross_user_generalization']


def test_replay_does_not_assume_pts_equals_elapsed(tmp_path):
    root=tmp_path/'session';root.mkdir();write_json(root/'session.json',{'schema_version':'temporal-pilot-v2','session_id':'test','trial_ids':[]})
    with pytest.raises(ValueError,match='unverified'):replay(root,tmp_path/'replay')


def test_native_contracts_and_no_microphone():
    base=Path('mobile_pilot/app/src/main')
    manifest=(base/'AndroidManifest.xml').read_text()
    assert 'RECORD_AUDIO' not in manifest
    import xml.etree.ElementTree as ET
    xml=ET.fromstring(manifest); ns='{http://schemas.android.com/apk/res/android}'; tools='{http://schemas.android.com/tools}'
    requested=[r.get(ns+'name') for r in xml.findall('uses-permission') if r.get(tools+'node')!='remove']
    assert requested==['android.permission.CAMERA']
    video=(base/'java/org/usercamera/mobilepilot/FrontVideoRecorder.kt').read_text()
    assert '.withAudioEnabled(' not in video
    assert 'VideoRecordEvent.Finalize' in video and 'KEEP_ONLY_LATEST' in video
    view=(base/'java/org/usercamera/mobilepilot/StimulusView.kt').read_text()
    assert 'ACTION_MOVE' in view and 'getHistoricalEventTime' in view and 'getPointerId' in view


def test_merged_manifest_has_no_network_or_microphone():
    import xml.etree.ElementTree as ET
    path=Path('mobile_pilot/app/build/intermediates/merged_manifests/debug/processDebugManifest/AndroidManifest.xml')
    if not path.exists():pytest.skip('Build Android APK to inspect actual merged permissions')
    requested=[r.get('{http://schemas.android.com/apk/res/android}name') for r in ET.parse(path).getroot().findall('uses-permission')]
    assert not set(requested)&{'android.permission.INTERNET','android.permission.ACCESS_NETWORK_STATE','android.permission.RECORD_AUDIO'}


def test_touch_clock_error_bound():
    from usercamera.pilot_video import touch_clock_valid
    row={'action':'move','raw_uptime_ms':100,'event_clock_offset_ns':10000,'timestamp_ns':100010000,'mapping_uncertainty_ns':1000000}
    assert touch_clock_valid(row)
    row['timestamp_ns']+=1000001
    assert not touch_clock_valid(row)


def test_rotation_and_raw_vs_preview_mirror_declarations():
    from usercamera.pilot_video import validate_orientation
    s={'width':720,'height':1280,'rotation_degrees':90,'mirrored':False}
    assert validate_orientation(s,{'raw_frames_mirrored':False,'preview_mirrored':True})==[1280,720]
    s['mirrored']=True
    with pytest.raises(ValueError,match='mirror'):validate_orientation(s,{'raw_frames_mirrored':False})
    s.update(mirrored=False,rotation_degrees=45)
    with pytest.raises(ValueError,match='rotation'):validate_orientation(s,{'raw_frames_mirrored':False})


def test_v1_mock_replay_keeps_evidence_tier(tmp_path):
    result=replay('mobile_pilot/mock_sessions/mock_s00',tmp_path/'replay')
    index=Path(result['replay'])
    data=json.loads((index.parent/'data.js').read_text()[len('const DATA='):-1])
    assert data['legacy'] and data['evidence_tier']=='mock' and data['frames']
    assert 'FABRICATED FIXTURE' in index.read_text()


def test_verified_device_smoke_is_not_research_data(tmp_path):
    root=tmp_path/'inputs';root.mkdir()
    write_jsonl(root/'windows_v2.jsonl',[{'participant_id':'p1','clock_alignment_usable':True,'evidence_tier':'device_automated_smoke'}])
    result=evaluate_v2(root,tmp_path/'out')
    assert result['status']=='blocked_non_research_evidence'


def test_evaluation_rejects_mixed_evidence(tmp_path):
    root=tmp_path/'inputs';root.mkdir()
    write_jsonl(root/'windows_v2.jsonl',[
        {'participant_id':'p1','clock_alignment_usable':False,'evidence_tier':'mock'},
        {'participant_id':'p2','clock_alignment_usable':False,'evidence_tier':'real_device_recording'}])
    with pytest.raises(ValueError,match='Never mix'):evaluate_v2(root,tmp_path/'out')


def test_gru_prefix_ui_is_strictly_before_cutoff(tmp_path,monkeypatch):
    from usercamera import pilot_inputs_v2 as module
    root=tmp_path/'unit_session';d=root/'trials'/'trial';d.mkdir(parents=True)
    write_json(root/'session.json',{'schema_version':'temporal-pilot-v2','participant_id':'unit_fixture','session_id':'unit_fixture','trial_ids':['trial'],'evidence_tier':'device_automated_smoke'})
    write_json(d/'trial_meta.json',{'task':'visual_search','status':'completed','onset_ns':0,'offset_ns':10_000_000_000,'template_id':'template'})
    e={'element_id':'target','bounding_box_px':[100,100,200,200],'clickable_region_px':[100,100,200,200],
       'font_glyph_height_px':20,'actual_glyph_height_px':20,'visual_contrast':21,'text':'target'}
    first={'timestamp_ns':0,'view_size_px':[1000,2000],'target_element_id':'target','elements':[e]}
    boundary=deepcopy(first);boundary['timestamp_ns']=1_000_000_000;boundary['elements'][0]['actual_glyph_height_px']=100
    write_jsonl(d/'ui_states.jsonl',[first,boundary]);write_jsonl(d/'touch_events.jsonl',[])
    monkeypatch.setattr(module,'inspect_folder',lambda _: {'videos':[]})
    module.prepare_inputs(root,tmp_path/'output',None,allow_estimated=True,run_face=False)
    rows=[json.loads(line) for line in (tmp_path/'output'/'windows_v2.jsonl').read_text().splitlines()]
    prefix=next(r for r in rows if r['mode']=='prefix_1s')
    assert prefix['screen']['glyph_height_px']==20
    assert prefix['sequence'][-1]['screen']['glyph_height_px']==20
