"""Raw session IO, explicit clock mapping, corruption checks and non-human fixtures."""
import json
import math
import tempfile
import zipfile
from contextlib import contextmanager
from collections import Counter
from pathlib import Path
import numpy as np
from PIL import Image
from .io import read_jsonl,write_json,write_jsonl,sha256


def safe_path(root,relative):
    root=Path(root).resolve();p=(root/relative).resolve()
    if not p.is_relative_to(root):raise ValueError('Path escapes session')
    return p


@contextmanager
def session_folder(path):
    path=Path(path)
    if path.is_dir():yield path;return
    with tempfile.TemporaryDirectory(prefix='pilot_import_') as tmp:
        with zipfile.ZipFile(path) as z:
            if sum(i.file_size for i in z.infolist())>2*1024**3:raise ValueError('Session ZIP exceeds 2GiB uncompressed')
            for i in z.infolist():
                safe_path(tmp,i.filename)
                if (i.external_attr>>16)&0o170000==0o120000:raise ValueError('ZIP symlink is not supported')
            z.extractall(tmp)
        candidates=list(Path(tmp).rglob('session.json'))
        if len(candidates)!=1:raise ValueError('ZIP must contain exactly one session')
        yield candidates[0].parent


def read_trial(folder):
    folder=Path(folder)
    return {'meta':json.loads((folder/'trial_meta.json').read_text()),'feedback':json.loads((folder/'feedback.json').read_text()),
            'camera':read_jsonl(folder/'camera_frames.jsonl'),'ui':read_jsonl(folder/'ui_states.jsonl'),
            'touch':read_jsonl(folder/'touch_events.jsonl')}


def monotonic(rows,key,strict=False):
    t=[r[key] for r in rows]
    if any(type(v) is not int or v<0 for v in t):raise ValueError('Invalid integer monotonic timestamp: '+key)
    if any(b<=a if strict else b<a for a,b in zip(t,t[1:])):raise ValueError('Nonmonotonic timestamps: '+key)


def map_camera_frame(row,allow_estimated=False):
    sensor=row['sensor_timestamp_ns'];arrival=row['arrival_elapsed_ns']
    if row['clock_source']=='REALTIME':
        if row.get('mapped_timestamp_ns')!=sensor:raise ValueError('REALTIME capture must use sensor elapsedRealtime timestamp')
        if arrival<sensor:raise ValueError('Capture timestamp later than arrival')
        return sensor,0,'shared_clock'
    if row['clock_source']!='UNKNOWN':raise ValueError('Unknown sensor time source enum')
    mapping=row.get('clock_mapping',{})
    if mapping.get('validated'):
        if mapping.get('validation_method')!='independent_capture_clock_pairs' or len(mapping.get('anchors',[]))<3:
            raise ValueError('UNKNOWN clock requires independent validation anchors')
        slope,offset=float(mapping['slope']),float(mapping['offset_ns']);bound=float(mapping['max_error_ns'])
        if not .99<=slope<=1.01 or bound<0:raise ValueError('Invalid clock mapping')
        error=max(abs(slope*a['sensor_ns']+offset-a['reference_capture_elapsed_ns']) for a in mapping['anchors'])
        if error>bound:raise ValueError('Clock mapping exceeds stated error bound')
        return int(slope*sensor+offset),bound,'independent_mapping'
    if allow_estimated and row.get('mapped_timestamp_ns') is not None:
        return row['mapped_timestamp_ns'],None,'estimated_unvalidated'
    return None,None,'unresolved_clock'


def validate_feedback(feedback,meta,evidence):
    if meta['task']=='fixation' or meta['status'].startswith('aborted'):
        return False
    if feedback.get('status')=='missing':return False
    expected='mock_self_report_fixture' if evidence=='mock' else 'self_report'
    if feedback.get('label_source')!=expected:raise ValueError('Difficulty label provenance must be independent self-report')
    if type(feedback.get('difficulty_rating')) is not int or feedback.get('difficulty_rating') not in [1,2,3,4,5]:raise ValueError('Difficulty rating must be integer1..5')
    if feedback.get('difficulty_type') not in ['visual','motor','navigation','semantic','none']:raise ValueError('Invalid difficulty type')
    if not isinstance(feedback.get('wants_help'),bool):raise ValueError('Missing help preference')
    if feedback.get('preferred_assistance') not in ['zoom','highlight','explain','none']:raise ValueError('Invalid assistance preference')
    monotonic([{'t':feedback['timestamp_ns']}],'t')
    if feedback['timestamp_ns']<meta['offset_ns']:raise ValueError('Feedback precedes trial offset')
    return True


def verify_folder(root,allow_mock=False,allow_estimated_clock=False):
    root=Path(root);s=json.loads((root/'session.json').read_text())
    if s.get('schema_version')!='temporal-pilot-v1':raise ValueError('Unsupported session schema')
    if s.get('evidence_tier') not in ['mock','real_device_recording']:raise ValueError('Invalid evidence tier')
    if s['evidence_tier']=='mock' and not allow_mock:raise ValueError('Mock session requires explicit --allow-mock')
    if s.get('clock')!='elapsed_realtime_ns':raise ValueError('Session requires elapsedRealtime nanosecond clock')
    if s.get('status') not in ['stopped','interrupted']:raise ValueError('Session must be stopped/exported before offline verification')
    if not s.get('participant_id') or not s.get('session_id'):raise ValueError('Missing participant/session identity')
    if len(set(s['trial_ids']))!=len(s['trial_ids']):raise ValueError('Duplicate trial IDs')
    report={'session_id':s['session_id'],'participant_id':s['participant_id'],'evidence_tier':s['evidence_tier'],
        'trials':[],'errors':[],'warnings':[],'physical_sync_proven':False,'clock_alignment_usable':True,
        'note':'Clock mapping checks do not prove display photon timing, fixation compliance, consent, or true difficulty onset.'}
    events=read_jsonl(root/'session_events.jsonl');monotonic(events,'timestamp_ns')
    exported=root/'export_manifest.json'
    if exported.exists():
        m=json.loads(exported.read_text());ids=set()
        for r in m['files']:
            p=safe_path(root,r['path'])
            if r['path'] in ids:raise ValueError('Duplicate export path')
            ids.add(r['path'])
            if not p.is_file() or sha256(p)!=r['sha256'] or p.stat().st_size!=r['bytes']:raise ValueError('Export file corruption: '+r['path'])
        actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p.name!='export_manifest.json'}
        if actual!=ids:raise ValueError('Export manifest omits files')
    previous_offset=-1
    for trial_id in s['trial_ids']:
        folder=safe_path(root,'trials/'+trial_id);t=read_trial(folder);m=t['meta'];start,end=m['onset_ns'],m['offset_ns']
        monotonic([{'t':start},{'t':end}],'t')
        if s['evidence_tier']!='mock' and (folder/'mock_camera_observations.jsonl').exists():raise ValueError('Fabricated observations cannot be relabeled as real')
        if len({f['frame_id'] for f in t['camera']})!=len(t['camera']):raise ValueError('Duplicate camera frame IDs')
        if m['trial_id']!=trial_id or m['session_id']!=s['session_id'] or m['participant_id']!=s['participant_id']:raise ValueError('Trial/session ownership mismatch')
        if not 0<=start<=end or start<previous_offset:raise ValueError('Invalid/overlapping trial timestamps')
        previous_offset=end
        for rows,key,strict in [(t['ui'],'timestamp_ns',False),(t['touch'],'timestamp_ns',False),(t['camera'],'sensor_timestamp_ns',True),(t['camera'],'arrival_elapsed_ns',False)]:monotonic(rows,key,strict)
        if not t['ui']:raise ValueError('Missing UI render state')
        for state in t['ui']:
            if state.get('render_valid') is False and not m['status'].startswith('aborted'):raise ValueError('Rendered glyphs overflow controlled UI')
            if not start<=state['timestamp_ns']<=end:raise ValueError('UI state outside trial')
            ids={e['element_id'] for e in state['elements']}
            if state['target_element_id'] not in ids:raise ValueError('Missing screen target bbox')
            for e in state['elements']:
                if e.get('render_timestamp_ns',state['timestamp_ns'])!=state['timestamp_ns']:raise ValueError('Element render timestamp differs from containing state')
                x0,y0,x1,y1=e['bounding_box_px'];w,h=state['view_size_px']
                if not (0<=x0<x1<=w and 0<=y0<y1<=h):raise ValueError('Target/element bounding box out of view')
            if state.get('screenshot_path'):
                with Image.open(safe_path(folder,state['screenshot_path'])) as im:im.verify()
                with Image.open(safe_path(folder,state['screenshot_path'])) as im:
                    if list(im.size)!=state['view_size_px']:raise ValueError('Screenshot dimensions disagree with UI state')
        for action in t['touch']:
            tolerance=action.get('mapping_uncertainty_ns',0)
            if not start-tolerance<=action['timestamp_ns']<=end+tolerance:raise ValueError('Touch outside trial')
            if action['action'] not in ['down','up','cancel','help_request']:raise ValueError('Unknown action')
            # Android uptime events require explicit elapsedRealtime mapping, even though they are both monotonic.
            if 'raw_uptime_ms' in action:
                mapped=action['raw_uptime_ms']*1000000+action['event_clock_offset_ns']
                if abs(mapped-action['timestamp_ns'])>action['mapping_uncertainty_ns']:raise ValueError('Touch clock mapping inconsistent')
        usable=[];statuses=Counter();sensor=[];jitter=[];outside=0;bounds=[]
        for frame in t['camera']:
            ts,bound,status=map_camera_frame(frame,allow_estimated_clock);statuses[status]+=1
            if ts is None or status=='estimated_unvalidated':report['clock_alignment_usable']=False
            if bound is not None:bounds.append(bound)
            if ts is not None and not start<=ts<=end:outside+=1
            if frame['status']=='recorded':
                p=safe_path(folder,frame['path'])
                if p.suffix.lower() in ['.mp4','.mov','.mkv']:raise ValueError('MP4 import not implemented; provide decoded frame sequence with independently verified capture timestamps, never playback PTS')
                if not p.is_file() or sha256(p)!=frame['sha256']:raise ValueError('Camera frame missing/corrupt')
                with Image.open(p) as im:im.verify()
                with Image.open(p) as im:
                    if list(im.size)!=[frame['width'],frame['height']]:raise ValueError('Frame dimensions inconsistent')
                sensor.append(frame['sensor_timestamp_ns'])
                if ts is not None:usable.append(ts)
            elif frame['status'] not in ['sampled_out','write_error','pre_onset']:raise ValueError('Unknown frame status')
            if frame['arrival_elapsed_ns']>=frame['sensor_timestamp_ns'] and frame['clock_source']=='REALTIME':jitter.append(frame['arrival_elapsed_ns']-frame['sensor_timestamp_ns'])
        monotonic([{'t':v} for v in usable],'t',True)
        if not sensor:report['warnings'].append(trial_id+': no recorded camera frames')
        dt=np.diff(sensor)/1e9;fps=(len(sensor)-1)/((sensor[-1]-sensor[0])/1e9) if len(sensor)>1 else None
        gaps=int(np.sum(np.maximum(0,np.rint(dt/np.median(dt)).astype(int)-1))) if len(dt) and np.median(dt)>0 else None
        labeled=validate_feedback(t['feedback'],m,s['evidence_tier'])
        report['trials'].append({'trial_id':trial_id,'task':m['task'],'status':m['status'],'recorded_frames':len(sensor),
            'camera_records':len(t['camera']),'frame_statuses':dict(Counter(f['status'] for f in t['camera'])),
            'actual_saved_fps':fps,'estimated_saved_frame_gaps':gaps,'gap_count_is_exact_driver_drops':False,
            'out_of_trial_camera_records':outside,'clock_status_counts':dict(statuses),
            'capture_to_arrival_p95_ms':float(np.quantile(jitter,.95)/1e6) if jitter else None,
            'synchronization_error_bound_ns':max(bounds) if bounds and len(bounds)==len(t['camera']) else None,
            'sync_bound_scope':'clock mapping only, not physical camera-display alignment',
            'camera_interruptions':[e for e in events if start<=e['timestamp_ns']<=end and
                (e.get('type') in ['camera_analysis_error','camera_unavailable'] or e.get('type')=='camera_state' and
                 any(v in e.get('detail','') for v in ['CLOSED','PENDING_OPEN','error=1','error=2','error=3','error=4','error=5']))],
            'touch_event_count':len(t['touch']),'ui_state_count':len(t['ui']),
            'camera_missing':not sensor,'has_independent_trial_label':labeled,'label_resolution':'trial_only'})
    report['missing_camera_trial_fraction']=float(np.mean([t['camera_missing'] for t in report['trials']])) if report['trials'] else None
    if not any(t['recorded_frames'] for t in report['trials']):report['clock_alignment_usable']=False
    return report


def verify_session(path,output='reports/pilot',allow_mock=False,allow_estimated_clock=False):
    with session_folder(path) as root:r=verify_folder(root,allow_mock,allow_estimated_clock)
    write_json(Path(output)/'quality'/f"{r['session_id']}.json",r)
    return r


def export_manifest(folder):
    folder=Path(folder)
    write_json(folder/'export_manifest.json',{'files':[{'path':str(p.relative_to(folder)),'bytes':p.stat().st_size,'sha256':sha256(p)}
            for p in sorted(folder.rglob('*')) if p.is_file() and p.name!='export_manifest.json']})


def make_mock_sessions(output,sessions=4,trials_per_session=10):
    """Explicitly fabricated IO fixtures, never human recordings or H2 evidence."""
    from .pilot_stimuli import build_protocol,render_trial
    output=Path(output);created=[]
    for session_index in range(sessions):
        rng=np.random.default_rng(800+session_index);sid=f'mock_s{session_index:02d}';folder=output/sid
        if folder.exists():raise ValueError('Refuse to overwrite mock session: '+str(folder))
        protocol=build_protocol(100+session_index);tasks=[protocol['trials'][0]]+[t for t in protocol['trials'] if t['task']=='visual_search'][:trials_per_session]
        base=(session_index+1)*100000000000;ids=[]
        for idx,t in enumerate(tasks):
            trial_id=t['trial_id'];ids.append(trial_id);d=folder/'trials'/trial_id;d.mkdir(parents=True)
            start=base+idx*10000000000;end=start+4000000000
            meta={'trial_id':trial_id,'participant_id':'mock_person','session_id':sid,'task':t['task'],'template_id':t['template_id'],
                'onset_ns':start,'offset_ns':end,'status':'completed','stimulus':t,'outcome':{'success':True,'completion_time_ms':4000,'misclicks':0,'help_requests':0}}
            write_json(d/'trial_meta.json',meta);render_trial(t,d/'stimulus.png')
            # Static reconstruction JSON is a separate reference artifact, not camera evidence.
            ui={'timestamp_ns':start,'timestamp_kind':'mock_draw_callback','view_size_px':[1080,1920],
                'view_origin_screen_px':[0,0],'page_id':t['page_id'],'elements':[{**e,'render_timestamp_ns':start} for e in t['elements']],'target_element_id':t['target_element_id'],
                'screenshot_path':'stimulus.png'}
            write_jsonl(d/'ui_states.jsonl',[ui]);target=next(e for e in t['elements'] if e['role']=='target');box=target['clickable_region_px']
            x,y=(box[0]+box[2])/2,(box[1]+box[3])/2
            actions=[] if t['task']=='fixation' else [{'timestamp_ns':start+3500000000+j*10000000,'action':a,'x_px':x,'y_px':y,
                 'element_id':target['element_id'],'correct_target_hit':True} for j,a in enumerate(['down','up'])]
            write_jsonl(d/'touch_events.jsonl',actions);frames=[];obs=[]
            for j in range(20):
                if j==7:continue
                ts=start+j*200000000;path=d/'frames'/f'{j:06d}.jpg';path.parent.mkdir(exist_ok=True)
                arr=np.tile(np.arange(64,dtype=np.uint8)*4,(64,1));Image.fromarray(np.roll(arr,j,axis=1)).convert('RGB').save(path)
                frames.append({'frame_id':j,'sensor_timestamp_ns':ts,'arrival_elapsed_ns':ts+12000000,
                    'mapped_timestamp_ns':ts,'clock_source':'REALTIME','mapping_status':'shared_clock','status':'recorded',
                    'path':str(path.relative_to(d)),'width':64,'height':64,'rotation_degrees':0,'sha256':sha256(path)})
                obs.append({'frame_id':j,'timestamp_ns':ts,'mock':True,'face_present':j!=11,'face_detection_confidence':None,
                    'yaw_deg':float(4*np.sin(j/5)+rng.normal()),'pitch_deg':float(2*np.cos(j/5)), 'roll_deg':0.,
                    'face_scale':float(.3+.01*np.sin(j/8)),'head_x':float(.5+.01*np.cos(j/4)),'head_y':.45,
                    'eye_landmark_visibility':None,'eye_in_frame_fraction_proxy':1.,'gaze_region':None,'gaze_confidence':None,
                    'frame_quality_laplacian':50.,'feature_source':'fabricated_mock_observations'})
            write_jsonl(d/'camera_frames.jsonl',frames);write_jsonl(d/'mock_camera_observations.jsonl',obs)
            feedback={'status':'not_applicable'} if t['task']=='fixation' else {'status':'provided','timestamp_ns':end+1000000000,
                'label_source':'mock_self_report_fixture','difficulty_rating':1+(idx+session_index)%5,'difficulty_type':'visual',
                'wants_help':bool(idx%2),'preferred_assistance':'highlight' if idx%2 else 'none'}
            write_json(d/'feedback.json',feedback)
        write_json(folder/'session.json',{'schema_version':'temporal-pilot-v1','participant_id':'mock_person','session_id':sid,
            'evidence_tier':'mock','clock':'elapsed_realtime_ns','trial_ids':ids,'status':'stopped','created_ns':base,'stopped_ns':base+len(tasks)*10000000000,
            'device':{'model':'NON_HUMAN_TEST_FIXTURE','screen_size_px':[1080,1920],'density':3.,'camera_orientation':0},
            'camera':{'available':True,'format':'jpeg_frame_sequence','target_saved_fps':5}})
        write_jsonl(folder/'session_events.jsonl',[]);export_manifest(folder);created.append(str(folder))
    return created
