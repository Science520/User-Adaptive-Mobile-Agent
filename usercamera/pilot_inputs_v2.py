"""v2 inputs and strictly pre-help fixed prefixes. No automatic training on one participant."""
import json
from pathlib import Path
from .io import read_jsonl,write_json,write_jsonl
from .pilot_session import session_folder
from .pilot_video import inspect_folder,optional_rows,video_frames,mapping_anchors,estimate_elapsed,safe_path
from .pilot_features import FaceLandmarkerBackend,camera_summary,screen_summary,action_summary

INPUT_CONFIGS={'A':'single_frame_user_image','B':'short_video_frame_sequence','C':'temporal_face_head_eye_features'}
MODELS={'M0':'Screen','M1':'Screen + Actions','M2':'Screen + Actions + Single User Frame',
        'M3':'Screen + Actions + Temporal User Features','M4':'Screen + Actions + Video Encoder',
        'M5':'Screen + Actions + mismatched User Stream'}


def causal_prefix(meta,touch,seconds):
    cutoff=meta['onset_ns']+int(seconds*1e9)
    if cutoff>=meta['offset_ns']:return None,'trial_ended_before_or_at_prefix'
    helps=sorted(t['timestamp_ns'] for t in touch if t['action']=='help_request')
    if helps and cutoff>=helps[0]:return None,'help_at_or_before_prefix; not a pre-help prediction'
    # Strict boundary: an event exactly at cutoff is excluded.
    actions=[t for t in touch if t['timestamp_ns']<cutoff and t['action']!='help_request']
    return {'cutoff_ns':cutoff,'actions':actions,'future_help':int(any(t>cutoff for t in helps)),
            'label_time_ns':helps[0] if helps else meta['offset_ns']},None


def prepare_inputs(path,output,model,allow_estimated=False,run_face=True):
    destination=Path(output)
    if destination.exists():raise ValueError('Input output exists; choose a new directory')
    with session_folder(path) as root:
        quality=inspect_folder(root);session=json.loads((root/'session.json').read_text())
        if session['schema_version']!='temporal-pilot-v2':raise ValueError('Use existing pilot-extract-features for legacy JPEG sessions')
        if not allow_estimated:raise ValueError('Unverified PTS mapping; use explicit --allow-estimated-clock for diagnostic extraction only')
        destination.mkdir(parents=True);frames=[];windows=[];excluded=[]
        backend=None
        try:
            for video in quality['videos']:
                if backend:backend.close()
                backend=FaceLandmarkerBackend(model) if run_face else None
                for decoded in video_frames(safe_path(root,video['path'])):
                    # 5Hz offline sampling. Encoded MP4 remains the complete source.
                    if decoded['index']%max(1,round(video['decoded_fps']/5))!=0:continue
                    pts=decoded['pts_us'];mapped=estimate_elapsed(pts,video['first_pts_us'],video['mapping_anchors'])
                    if mapped is None:continue
                    image=decoded['frame'].to_image()
                    rotation=video.get('rotation_degrees',0)
                    if rotation:image=image.rotate(-rotation,expand=True)
                    observation=backend.extract(image,pts*1000) if backend else {'face_present':False,'feature_source':'unavailable'}
                    appearance=[float(v)/255 for v in image.convert('L').resize((16,12)).getdata()]
                    frames.append({**observation,'timestamp_ns':mapped,'available_ns':mapped,
                        'availability_kind':'offline_replay_capture_only_not_live_latency',
                        'video_path':video['path'],'pts_us':pts,'clock_alignment_usable':False,'appearance_gray16x12':appearance})
        finally:
            if backend:backend.close()
        for tid in session['trial_ids']:
            d=root/'trials'/tid;m=json.loads((d/'trial_meta.json').read_text());touch=optional_rows(d/'touch_events.jsonl');ui=optional_rows(d/'ui_states.jsonl')
            if m['task']!='visual_search' or m['status'].startswith('aborted'):continue
            for seconds in [1,2,3,5]:
                prefix,error=causal_prefix(m,touch,seconds)
                if error:excluded.append({'trial_id':tid,'prefix_s':seconds,'reason':error});continue
                cutoff=prefix['cutoff_ns'];selected=[f for f in frames if m['onset_ns']<=f['timestamp_ns']<cutoff]
                first=selected[0] if selected else None
                sequence=[]
                for j in range(6):
                    end=m['onset_ns']+int((cutoff-m['onset_ns'])*(j+1)/6)
                    sequence.append({'screen':screen_summary(ui,end-1),'actions':action_summary(prefix['actions'],m['onset_ns'],end-1),
                        'user':camera_summary(selected,m['onset_ns'],end-1)})
                windows.append({'id':session['session_id']+'/'+tid+f'/prefix_{seconds}s','participant_id':session['participant_id'],
                    'session_id':session['session_id'],'trial_id':tid,'template_id':m['template_id'],'mode':f'prefix_{seconds}s',
                    'input_start_ns':m['onset_ns'],'input_end_ns':cutoff,'label_time_ns':prefix['label_time_ns'],
                    'target_future_help':prefix['future_help'],'label_source':'actual_help_request_or_observed_trial_end',
                    'screen':screen_summary(ui,cutoff-1),'actions':action_summary(prefix['actions'],m['onset_ns'],cutoff-1),
                    'user':camera_summary(selected,m['onset_ns'],cutoff-1),'sequence':sequence,
                    'single_frame_appearance':first['appearance_gray16x12'] if first else None,
                    'video_frames':[{'video_path':f['video_path'],'pts_us':f['pts_us']} for f in selected],
                    'input_configs':INPUT_CONFIGS,'evidence_tier':session['evidence_tier'],'clock_alignment_usable':False})
        write_jsonl(destination/'camera_features.jsonl',frames);write_jsonl(destination/'windows_v2.jsonl',windows)
        report={'schema_version':'pilot-inputs-v2','models':MODELS,'input_configs':INPUT_CONFIGS,'windows':len(windows),'excluded':excluded,
            'single_frame_encoder':'weak raw grayscale16x12; not gaze-specific or pretrained video encoder',
            'video_encoder_status':'interface_only; not trained with insufficient synchronized independent groups',
            'mapping_status':'estimated_unverified','physical_sync_uncertainty_ns':None,'participants':1,
            'cross_user_generalization':False,'training_status':'blocked_unverified_sync_and_insufficient_groups',
            'fixed_prefixes_s':[1,2,3,5],'future_help_boundary':'all model inputs strictly before first observed help and prefix cutoff'}
        write_json(destination/'inputs.json',report);return report


def evaluate_v2(features,output,algorithms=('logistic','hist_gradient_boosting','gru')):
    """Only verified synchronized windows can enter future evaluation; keep v1 meanings unchanged."""
    import numpy as np
    from .pilot_temporal import split_windows,flatten,mismatched_user,fit_tabular,fit_gru,probability_metrics
    from .pilot_features import USER_KEYS
    rows=[r for p in sorted(Path(features).rglob('windows_v2.jsonl')) for r in read_jsonl(p)]
    if not rows:raise ValueError('No v2 windows')
    if not set(algorithms)<={'logistic','hist_gradient_boosting','gru'}:raise ValueError('Unknown algorithm')
    participants={r['participant_id'] for r in rows}
    tiers={r.get('evidence_tier','unknown') for r in rows}
    if len(tiers)!=1:raise ValueError('Never mix research, device-smoke and mock evidence in one evaluation')
    result={'models':MODELS,'participants':len(participants),'supports_cross_user_generalization':False,'modes':{},'M4_status':'not_run; no trained video encoder'}
    if any(not r.get('clock_alignment_usable',False) for r in rows):
        result.update(status='blocked_unverified_sync',reason='Diagnostic PTS estimates cannot support synchronized fusion metrics')
    elif tiers!={'real_device_recording'}:
        result.update(status='blocked_non_research_evidence',reason='Device-smoke/mock/unknown recordings are not research difficulty evidence')
    else:
        for row in rows:
            if not row['input_start_ns']<=row['input_end_ns']<row['label_time_ns']:raise ValueError('Invalid future-help causal window')
            if row['target_future_help'] not in [0,1]:raise ValueError('Future-help label must be binary')
        result['status']='evaluated_or_insufficient_groups'
        for mode in ['prefix_1s','prefix_2s','prefix_3s','prefix_5s']:
            selected=[r for r in rows if r['mode']==mode];_,folds,scope=split_windows(selected)
            result['modes'][mode]={'scope':scope,'models':{}}
            for name in MODELS:
                if name=='M4':continue
                predictions={a:[] for a in algorithms};labels=[]
                def matrices(indices):
                    donor=mismatched_user(selected,indices) if name=='M5' else {i:i for i in indices}
                    vectors=[];sequences=[]
                    for i in indices:
                        r=selected[i];d=selected[donor[i]] if donor[i] is not None else None
                        user=d['user'] if d else {k:None for k in USER_KEYS}
                        appearance=r.get('single_frame_appearance') or [None]*192
                        letters='S' if name=='M0' else 'SA' if name in ['M1','M2'] else 'SAU'
                        vectors.append(flatten({**r,'user':user},letters)+([np.nan if v is None else v for v in appearance] if name=='M2' else []))
                        seq=[]
                        for j,step in enumerate(r['sequence']):
                            su=d['sequence'][j]['user'] if d else {k:None for k in USER_KEYS}
                            # Single-frame appearance stays constant; M3/M5 alone use temporal user states.
                            seq.append(flatten({**step,'user':su},letters)+([np.nan if v is None else v for v in appearance] if name=='M2' else []))
                        sequences.append(seq)
                    return np.asarray(vectors,float),np.asarray(sequences,float)
                for train,val,test in folds:
                    a,aseq=matrices(train);b,bseq=matrices(val);c,cseq=matrices(test)
                    y=np.array([selected[i]['target_future_help'] for i in train]);yv=np.array([selected[i]['target_future_help'] for i in val]);labels.extend(selected[i]['target_future_help'] for i in test)
                    for algorithm in algorithms:
                        p,_=fit_gru(aseq,y,bseq,yv,cseq) if algorithm=='gru' else fit_tabular(a,y,b,yv,c,algorithm)
                        predictions[algorithm].extend(p)
                result['modes'][mode]['models'][name]={a:probability_metrics(labels,p) for a,p in predictions.items() if p}
    dest=Path(output)/'temporal_v2_results.json'
    if dest.exists():raise ValueError('Results exist; no overwrite')
    write_json(dest,result);return result
