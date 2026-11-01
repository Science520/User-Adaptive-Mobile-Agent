"""Cached recent windows, with explicit masks and unresolved synchronization guards."""
import json,time
from pathlib import Path
import numpy as np
from .io import write_json,write_jsonl,read_jsonl,sha256
from .pilot_video import estimate_elapsed,mapping_anchors
from .pilot_features import screen_summary,action_summary

KEYS=['head_x','head_y','face_scale','yaw_proxy_deg','pitch_proxy_deg','roll_proxy_deg','eyeBlinkLeft','eyeBlinkRight']


def eligible_live(rows,start,cutoff):
    return [r for r in rows if r.get('timestamp_ns') is not None and start<=r['timestamp_ns']<cutoff and r['available_ns']<cutoff]


def recent_summary(rows):
    out={};good=[r for r in rows if r.get('face_present')]
    for key in KEYS:
        values=[r[key] for r in good if r.get(key) is not None]
        out[key+'_mean']=float(np.mean(values)) if values else None;out[key+'_std']=float(np.std(values)) if values else None
    scales=[r['face_scale'] for r in good if r.get('face_scale',0)>0]
    out['relative_scale_change']=scales[-1]/scales[0]-1 if scales else None
    velocities=[]
    for a,b in zip(good,good[1:]):
        dt=(b['timestamp_ns']-a['timestamp_ns'])/1e9
        if 0<dt<=1 and all(a.get(k) is not None and b.get(k) is not None for k in ['yaw_proxy_deg','pitch_proxy_deg','roll_proxy_deg']):
            velocities.append(np.linalg.norm([b[k]-a[k] for k in ['yaw_proxy_deg','pitch_proxy_deg','roll_proxy_deg']])/dt)
    out['euler_velocity_proxy_deg_s']=float(np.mean(velocities)) if velocities else None
    out['observations']=len(rows);out['face_fraction']=len(good)/len(rows) if rows else None;out['missing']=not bool(good)
    return out


def prepare_temporal_v3(session='test1030_20261030_144219',output='reports/pilot_v3/temporal',private='reports/pilot_v3/private/temporal'):
    root=Path(session);out=Path(output);priv=Path(private);out.mkdir(parents=True,exist_ok=True);priv.mkdir(parents=True,exist_ok=True)
    if (priv/'windows.jsonl').exists():raise ValueError('Preserve existing feature windows; choose another output')
    s=json.loads((root/'session.json').read_text())
    expected=json.loads(Path('reports/pilot_v3/audit_20261030/preservation.json').read_text())['source_sha256']['front_camera.mp4']
    if sha256(root/'front_camera.mp4')!=expected:raise ValueError('Temporal reference belongs to another video; prepare its matching audit first')
    live=read_jsonl(root/'live_face_features.jsonl');timeline=read_jsonl(root/'video_timeline.jsonl')
    pts=[r['pts_us'] for r in timeline if r['type']=='encoded_frame'];anchors=mapping_anchors(timeline,'front_camera.mp4');mapped=np.array([estimate_elapsed(p,pts[0],anchors) for p in pts],dtype=np.int64)
    offline=read_jsonl('reports/pilot_v3/private/audit_20261030/offline_face_observations.jsonl')
    windows=[];excluded=[];sequence=[];timestamps=[];offsets=[0]
    for tid in s['trial_ids']:
        d=root/'trials'/tid;m=json.loads((d/'trial_meta.json').read_text());feedback=json.loads((d/'feedback.json').read_text());ui=read_jsonl(d/'ui_states.jsonl');touch=read_jsonl(d/'touch_events.jsonl')
        if m['task']=='fixation' or m['status'].startswith('aborted'):continue
        help_times=sorted(r['timestamp_ns'] for r in touch if r['action']=='help_request')
        for prefix in [2,3,5]:
            cutoff=m['onset_ns']+prefix*1_000_000_000
            if cutoff>=m['offset_ns'] or (help_times and cutoff>=help_times[0]):
                excluded.append({'trial_id':tid,'decision_prefix_s':prefix,'reason':'task_ended_or_help_already_occurred'});continue
            for recent in [2,3,5]:
                start=max(m['onset_ns'],cutoff-recent*1_000_000_000);frames=eligible_live(live,start,cutoff)
                actions=[r for r in touch if start<=r['timestamp_ns']<cutoff and r['action']!='help_request']
                crops=[r for r in offline if r.get('face_box_normalized') and start<=estimate_elapsed(r['pts_us'],pts[0],anchors)<cutoff]
                crop=crops[-1] if crops else None
                clip_indices=np.flatnonzero((mapped>=start)&(mapped<cutoff));sampled=[];last=-10**30
                for i in clip_indices:
                    if mapped[i]-last>=250_000_000:sampled.append(int(i));last=int(mapped[i])
                row={'id':s['session_id']+'/'+tid+f'/p{prefix}_recent{recent}','label_schema_version':s.get('label_schema_version','legacy-unspecified'),'protocol_version':s.get('protocol_version',s['schema_version']),
                    'participant_id':s['participant_id'],'session_id':s['session_id'],'trial_id':tid,'template_id':m['template_id'],
                    'target_text':m['stimulus'].get('target_text') or next(e['text'] for e in m['stimulus']['elements'] if e['role']=='target'),
                    'decision_prefix_s':prefix,'recent_window_s':recent,'input_start_ns':int(start),'cutoff_ns':int(cutoff),
                    'actual_window_s':(cutoff-start)/1e9,'partial_window':cutoff-start<recent*1e9,
                    'screen':screen_summary(ui,cutoff-1),'touch_history':action_summary(actions,start,cutoff-1),'user':recent_summary(frames),
                    'label_future_help':int(any(t>cutoff for t in help_times)),
                    'label_self_report_difficulty':int(feedback['difficulty_rating']>=3) if feedback.get('status')=='provided' else None,
                    'label_source':'independent trial self-report; no-help is not no-difficulty','label_time_ns':feedback.get('timestamp_ns'),
                    'single_frame_face_crop':str(Path('data/derivatives/pilot_v3')/s['session_id']/'face_crops'/f'{crop["frame_index"]:06d}.jpg') if crop else None,
                    'appearance_availability':'offline capture-time representation; actual online compute latency not measured',
                    'short_video_clip':{'source':str(root/'front_camera.mp4'),'frame_indices':sampled,'pts_us':[pts[i] for i in sampled],'sampling':'past frames only, <=4Hz, no interpolation'},
                    'clock_alignment_usable':False,'physical_sync_status':'unverified','evidence_tier':s['evidence_tier']}
                windows.append(row)
                for frame in frames:
                    sequence.append([np.nan if frame.get(k) is None else frame[k] for k in KEYS]);timestamps.append(frame['timestamp_ns'])
                offsets.append(len(sequence))
    write_jsonl(priv/'windows.jsonl',windows)
    X=[]
    feature_keys=sorted(set(k for r in windows for k in r['user']))
    for r in windows:
        X.append([np.nan if r['user'].get(k) is None else float(r['user'][k]) for k in feature_keys])
    np.savez_compressed(priv/'feature_cache.npz',X=np.array(X,float),sequence=np.asarray(sequence,float),sequence_timestamps_ns=np.array(timestamps,np.int64),sequence_offsets=np.array(offsets,np.int64),feature_names=np.asarray(feature_keys),sequence_names=np.asarray(KEYS))
    start=time.perf_counter()
    with np.load(priv/'feature_cache.npz') as cache:shape=cache['X'].shape
    load_s=time.perf_counter()-start
    blockers=['unverified_encoded_video_to_elapsed_mapping','one_participant_one_session; no independent train/validation/test groups']
    report={'windows':len(windows),'excluded':excluded,'participants':1,'sessions':1,'scope':'within-person exploratory preparation only',
        'models':{'screen_only':'not_trained','screen_touch':'not_trained','screen_touch_temporal_user':'not_trained','single_frame_face':'representation_interface','short_video_clips':'sampled_frame_refs_not_large_video_transformer'},
        'train_status':'blocked','blockers':blockers,'recent_windows_s':[2,3,5],'decision_prefix_s':[2,3,5],
        'no_help_not_no_difficulty':True,'inputs_strictly_before_cutoff':True,'live_available_ns_checked':True,
        'unavailable_observations_have_masks_not_fabricated_interpolation':True,
        'npz_cache_bytes':(priv/'feature_cache.npz').stat().st_size,'raw_video_bytes':(root/'front_camera.mp4').stat().st_size,
        'cache_load_seconds':load_s,'X_shape':shape,'sequence_feature_keys':KEYS,'feature_keys':feature_keys,
        'blink_limit':'~2Hz Live features support blendshape dynamics proxies, not validated complete blink counts',
        'selection_bias':'short/easily completed trials excluded at longer prefixes; report excluded list, do not claim all-trial performance',
        'protocol_split_policy':'Do not mix v1/v2/v3 task definitions; group by protocol_version and participant/session before fitting'}
    write_json(out/'preparation.json',report)
    (out/'README.md').write_text('# Efficient temporal preparation\n\n'+json.dumps(report,ensure_ascii=False,indent=2)+'\n\n先一次性缓存Face/Head/Eye代理，再按实际timestamp与available_ns取最近2/3/5秒；单帧用截止前的预测ROI裁剪，短视频保留原始PTS采样引用。缺失以mask/NaN表示，不插值成真实观察。原始视频不重写，每epoch读紧凑cache。当前时间映射未验证，单人单Session，未训练或报告融合性能/跨用户可靠性。\n')
    return report

if __name__=='__main__':print(json.dumps(prepare_temporal_v3(),ensure_ascii=False,indent=2))
