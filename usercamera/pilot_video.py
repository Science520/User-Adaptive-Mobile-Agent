"""Local video verification/replay. Recorder callback mapping is explicitly unverified."""
import json,shutil,hashlib,tempfile
from pathlib import Path
from .io import read_jsonl,write_json,write_jsonl,sha256
from .pilot_session import session_folder,safe_path


def optional_rows(path):
    return read_jsonl(path) if Path(path).exists() else []


def verify_manifest(root):
    manifest=json.loads((root/'export_manifest.json').read_text())
    seen=set()
    for row in manifest['files']:
        if row['path'] in seen:raise ValueError('Duplicate manifest entry')
        seen.add(row['path']); p=safe_path(root,row['path'])
        if not p.is_file() or p.stat().st_size!=row['bytes'] or sha256(p)!=row['sha256']:raise ValueError('Corrupt/missing file: '+row['path'])
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name!='export_manifest.json'}
    if actual!=seen:raise ValueError('Unmanifested or missing session file')
    return len(seen)


def video_frames(path):
    try:import av
    except ImportError as e:raise ValueError('Install optional video dependency: pip install av==12.3.0') from e
    try:
        with av.open(str(path)) as container:
            streams=list(container.streams.video)
            if len(streams)!=1:raise ValueError('Exactly one video track required')
            stream=streams[0]
            for index,frame in enumerate(container.decode(stream)):
                if frame.pts is None:raise ValueError('Decoded frame has no PTS')
                yield {'index':index,'pts_us':int(frame.pts*frame.time_base*1000000),'frame':frame,
                       'width':frame.width,'height':frame.height,'codec':stream.codec_context.name,'audio_tracks':len(container.streams.audio)}
    except (OSError,RuntimeError) as e:raise ValueError('Video decode failed: '+str(e)) from e


def mapping_anchors(rows,path):
    # Callback time is NOT an independent physical capture timestamp. Pauses require piecewise offsets.
    anchors=[r for r in rows if r.get('path')==path and r.get('type') in ['start','resume']]
    return sorted(anchors,key=lambda r:r['recorded_duration_ns'])


def estimate_elapsed(pts_us,first_pts_us,anchors):
    relative=(pts_us-first_pts_us)*1000
    valid=[a for a in anchors if a['recorded_duration_ns']<=relative]
    if not valid:return None
    a=valid[-1]
    return int(a['timestamp_ns']+relative-a['recorded_duration_ns'])


def touch_coordinates_valid(row):
    if row.get('action')=='help_request':return True
    origin=row.get('view_origin_screen_px')
    if origin is None:return False
    return all(abs(row['screen_'+axis+'_px']-row[axis+'_px']-origin[i])<.01 for i,axis in enumerate(['x','y']))



def touch_clock_valid(row):
    if row.get('action')=='help_request':return True
    if any(k not in row for k in ['raw_uptime_ms','event_clock_offset_ns','mapping_uncertainty_ns','timestamp_ns']):return False
    bound=row['mapping_uncertainty_ns']
    return bound>=0 and abs(row['timestamp_ns']-(row['raw_uptime_ms']*1000000+row['event_clock_offset_ns']))<=bound


def validate_orientation(summary,camera):
    rotation=summary.get('rotation_degrees')
    if rotation not in [0,90,180,270]:raise ValueError('Invalid video rotation')
    if type(summary.get('mirrored')) is not bool:raise ValueError('Missing raw mirror declaration')
    if summary['mirrored']!=camera.get('raw_frames_mirrored'):raise ValueError('Raw mirror declarations disagree')
    width,height=summary['width'],summary['height']
    if width<=0 or height<=0:raise ValueError('Invalid video dimensions')
    return [height,width] if rotation in [90,270] else [width,height]

def inspect_folder(root):
    session=json.loads((root/'session.json').read_text())
    if session['schema_version']!='temporal-pilot-v2':
        from .pilot_session import verify_folder
        ignored=[str(p.relative_to(root)) for p in root.rglob('.DS_Store')]
        with tempfile.TemporaryDirectory(prefix='pilot_v1_readonly_') as tmp:
            clean=Path(tmp)/'session'
            shutil.copytree(root,clean,ignore=shutil.ignore_patterns('.DS_Store'))
            legacy=verify_folder(clean,allow_estimated_clock=True)
        return {'schema_version':session['schema_version'],'session_id':session['session_id'],'legacy':legacy,'videos':[],
                'ignored_os_metadata':ignored,'note':'Legacy JPEG format retained; original files untouched. No MP4 fabricated.'}
    if session.get('status') not in ['stopped','interrupted']:raise ValueError('Session must be stopped before verification')
    if session.get('evidence_tier') not in ['real_device_recording','device_automated_smoke']:raise ValueError('Unsupported evidence tier')
    if len(session['trial_ids'])!=len(set(session['trial_ids'])):raise ValueError('Duplicate trial IDs')
    checked=verify_manifest(root);rows=optional_rows(root/'video_timeline.jsonl');videos=[]
    for path in sorted({r['path'] for r in rows if r.get('type')=='file_summary'}):
        summary=next(r for r in reversed(rows) if r.get('type')=='file_summary' and r['path']==path)
        video=safe_path(root,path)
        if sha256(video)!=summary['sha256']:raise ValueError('Video summary hash mismatch')
        decoded=[{k:v for k,v in f.items() if k!='frame'} for f in video_frames(video)]
        if not decoded:raise ValueError('Empty video')
        pts=[r['pts_us'] for r in decoded]
        if any(b<=a for a,b in zip(pts,pts[1:])):raise ValueError('Non-increasing decoded PTS')
        if decoded[0]['audio_tracks']:raise ValueError('Audio present despite audio-disabled contract')
        if decoded[0]['codec']!='h264':raise ValueError('Expected H.264 video')
        encoded=[r['pts_us'] for r in rows if r.get('type')=='encoded_frame' and r.get('path')==path]
        if pts!=encoded:raise ValueError('Encoded frame timeline differs from decoded MP4 PTS')
        display_size=validate_orientation(summary,session['camera'])
        final=next((r for r in rows if r.get('type')=='finalize' and r.get('path')==path),None)
        if not final or not final.get('finalization_success'):raise ValueError('Video not successfully finalized')
        anchors=mapping_anchors(rows,path);start=estimate_elapsed(pts[0],pts[0],anchors);end=estimate_elapsed(pts[-1],pts[0],anchors)
        videos.append({**summary,'display_size_px':display_size,'decoded_frames':len(decoded),'decoded_duration_s':(pts[-1]-pts[0])/1e6,
            'decoded_fps':(len(pts)-1)*1e6/(pts[-1]-pts[0]) if len(pts)>1 else None,
            'estimated_elapsed_start_ns':start,'estimated_elapsed_end_ns':end,'mapping_anchors':anchors,
            'physical_sync_status':'unverified','sync_uncertainty_ns':None,
            'orientation_status':'container_metadata_checked; physical_upright_and_mirroring_require_visual_check',
            'count_matches':len(decoded)==summary['frame_count']})
    expected_mp4={p.relative_to(root).as_posix() for p in root.glob('*.mp4')}
    if expected_mp4!={v['path'] for v in videos}:raise ValueError('MP4 missing final inspection summary')
    if session.get('capture_mode')=='video' and session.get('camera',{}).get('available') and not videos:raise ValueError('Video camera available but no finalized MP4')
    trials=[];events=[];previous_offset=-1
    live=optional_rows(root/'live_face_features.jsonl')
    for trial_id in session['trial_ids']:
        d=safe_path(root,'trials/'+trial_id);m=json.loads((d/'trial_meta.json').read_text());ui=optional_rows(d/'ui_states.jsonl');touch=optional_rows(d/'touch_events.jsonl')
        if m['offset_ns']<m['onset_ns'] or m['onset_ns']<previous_offset:raise ValueError('Trial negative duration or overlap')
        if m['trial_id']!=trial_id or m['session_id']!=session['session_id'] or m['participant_id']!=session['participant_id']:raise ValueError('Trial ownership mismatch')
        previous_offset=m['offset_ns']
        jpeg=optional_rows(d/'camera_frames.jsonl')
        for frame in jpeg:
            if frame.get('status')=='recorded':
                from PIL import Image
                from .pilot_session import map_camera_frame
                map_camera_frame(frame,allow_estimated=True)
                with Image.open(safe_path(d,frame['path'])) as image:
                    image.load()
                    if list(image.size)!=[frame['width'],frame['height']]:raise ValueError('JPEG frame dimensions inconsistent')
        versions=[s['ui_state_version'] for s in ui]
        if len(versions)!=len(set(versions)):raise ValueError('Duplicate UI version')
        for state in ui:
            from PIL import Image
            with Image.open(safe_path(d,state['screenshot_path'])) as image:
                image.load()
                if list(image.size)!=state['view_size_px']:raise ValueError('UI screenshot dimensions differ')
        if any(not touch_coordinates_valid(t) for t in touch):raise ValueError('Invalid local-to-screen touch coordinates')
        if any(not touch_clock_valid(t) for t in touch):raise ValueError('Invalid touch clock mapping')
        for t in touch:
            if t['timestamp_ns']<m['onset_ns'] or t['timestamp_ns']>m['offset_ns']:raise ValueError('Touch outside trial')
            if 'ui_state_version' in t and t['ui_state_version'] not in versions:raise ValueError('Touch refers to missing UI version')
            if t.get('action')!='help_request':
                state=next(s for s in ui if s['ui_state_version']==t['ui_state_version'])
                if abs(t['normalized_x']-t['x_px']/state['view_size_px'][0])>.0001 or abs(t['normalized_y']-t['y_px']/state['view_size_px'][1])>.0001:
                    raise ValueError('Incorrect normalized touch coordinates')
        matches=[]
        for name,ts in [('onset',m['onset_ns']),('offset',m['offset_ns'])]+[(t['action'],t['timestamp_ns']) for t in touch]:
            candidates=[]
            for v in videos:
                for r in rows:
                    if r.get('type')=='encoded_frame' and r.get('path')==v['path']:
                        mapped=estimate_elapsed(r['pts_us'],v['first_pts_us'],v['mapping_anchors'])
                        if mapped is not None:candidates.append((abs(mapped-ts),v['path'],r['pts_us']))
            nearest=min(candidates) if candidates else None
            matches.append({'event':name,'timestamp_ns':ts,'nearest_estimated_frame_delta_ms':nearest[0]/1e6 if nearest else None,
                'video_path':nearest[1] if nearest else None,'pts_us':nearest[2] if nearest else None,'physical_sync_status':'unverified'})
        estimated_frames=sum(m['onset_ns']<=estimate_elapsed(r['pts_us'],v['first_pts_us'],v['mapping_anchors'])<=m['offset_ns']
            for v in videos for r in rows if r.get('type')=='encoded_frame' and r.get('path')==v['path'] and estimate_elapsed(r['pts_us'],v['first_pts_us'],v['mapping_anchors']) is not None)
        valid_face=[f for f in live if f.get('timestamp_ns') is not None and m['onset_ns']<=f['timestamp_ns']<=m['offset_ns'] and f.get('face_present') and f.get('face_fully_in_frame_proxy') and f.get('eye_in_frame_fraction_proxy')==1]
        trials.append({'jpeg_saved_frames':sum(f.get('status')=='recorded' for f in jpeg),'valid_live_face_observations':len(valid_face),'fixation_face_validity':'proxy_observed' if valid_face else 'unverified_or_face_missing', 'trial_id':trial_id,'task':m['task'],'status':m['status'],'estimated_video_frames':estimated_frames,
            'fixation_sufficient_frame_count':estimated_frames>=12 if m['task']=='fixation' else None,
            'gaze_truth':'instructed_target_only' if m['task']=='fixation' else None,
            'failure_reason': 'insufficient_estimated_video_frames' if m['task']=='fixation' and estimated_frames<12 else None,
            'events':matches})
    return {'schema_version':session['schema_version'],'session_id':session['session_id'],'participant_id':session['participant_id'],
        'evidence_tier':session['evidence_tier'],'manifest_files_checked':checked,'videos':videos,'trials':trials,
        'physical_sync_status':'unverified','sync_uncertainty_ns':None,
        'interpretation':'Nearest-frame residual checks estimated coverage only. They are not measured video/touch physical sync error.',
        'missing_live_features':not bool(live), 'live_feature_count':len(live),
        'live_face_present_count':sum(bool(r.get('face_present')) for r in live),
        'live_inference_latency_ms_mean':sum(r.get('inference_latency_ns',0) for r in live)/len(live)/1e6 if live else None,
        'supports_cross_user_generalization':False}


def verify_video(path,output='reports/pilot_v2'):
    with session_folder(path) as root:report=inspect_folder(root)
    destination=Path(output)/'quality'/((report.get('session_id') or Path(path).stem)+'.json')
    if destination.exists():raise ValueError('Output exists; choose independent output directory')
    write_json(destination,report);return report


def replay(path,output='reports/pilot_v2/private/replay',allow_estimated=False):
    with session_folder(path) as root:
        session=json.loads((root/'session.json').read_text());v2=session['schema_version']=='temporal-pilot-v2'
        if v2 and not allow_estimated:raise ValueError('PTS mapping is unverified; explicit --allow-estimated-clock required for diagnostic replay')
        destination=Path(output)/session['session_id']
        if destination.exists():raise ValueError('Replay destination exists; no overwrite')
        destination.mkdir(parents=True);shutil.copytree(root,destination/'session')
        timeline=optional_rows(root/'video_timeline.jsonl');trials=[]
        for tid in session['trial_ids']:
            d=root/'trials'/tid;m=json.loads((d/'trial_meta.json').read_text())
            trials.append({'id':tid,'onset':str(m['onset_ns']),'offset':str(m['offset_ns']),
                'ui':[{**s,'t':str(s['timestamp_ns'])} for s in optional_rows(d/'ui_states.jsonl')],
                'touch':[{**s,'t':str(s['timestamp_ns'])} for s in optional_rows(d/'touch_events.jsonl')]})
        videos=[];frames=[]
        if v2:
            for s in timeline:
                if s.get('type')=='file_summary':videos.append({'path':'session/'+s['path'],'first_pts_us':s['first_pts_us'],
                    'anchors':[{'elapsed':str(a['timestamp_ns']),'relative':str(a['recorded_duration_ns'])} for a in mapping_anchors(timeline,s['path'])]})
        else:
            for tid in session['trial_ids']:
                for f in optional_rows(root/'trials'/tid/'camera_frames.jsonl'):
                    if f.get('path') and f.get('mapped_timestamp_ns') is not None:
                        frames.append({'t':str(f['mapped_timestamp_ns']),'path':'session/trials/'+tid+'/'+f['path'], 'rotation':f.get('rotation_degrees',0)})
        data={'trials':trials,'videos':videos,'frames':frames,'legacy':not v2,
            'evidence_tier':session.get('evidence_tier','unknown'), 'pages':[{**r,'t':str(r['timestamp_ns'])} for r in optional_rows(root/'ui_states.jsonl') if not r.get('trial_id')]}
        (destination/'data.js').write_text('const DATA='+json.dumps(data,ensure_ascii=False)+';')
        (destination/'index.html').write_text(REPLAY_HTML)
    return {'replay':str(destination/'index.html'),'private_faces_copied_locally':True,'clock_mapping':'estimated_unverified' if v2 else 'legacy metadata mapping','upload':False}

REPLAY_HTML='''<!doctype html><meta charset="utf-8"><title>Local User–GUI replay</title>
<style>body{font:16px system-ui;background:#eee}section{display:flex;gap:16px}video,#camera{max-width:40vw;max-height:75vh}#stage{position:relative}#ui{max-height:75vh;max-width:45vw}#dot{position:absolute;width:15px;height:15px;border:3px solid red;border-radius:50%;pointer-events:none}pre{white-space:pre-wrap}</style>
<h2>本地回放 · PTS→elapsed 映射 UNVERIFIED</h2><p>仅用于诊断估计对齐；不代表测得的物理同步精度。界面图片来自导出 Session（证据层级见下方），已记录的说明/问卷/休息页也可回放。</p>
<p id="tier"></p><select id="segments"></select><section><video id="video" controls></video><img id="camera" hidden><div id="stage"><img id="ui"><span id="dot" hidden></span></div></section><input id="slider" type="range" min="0" value="0" style="width:90%" hidden><pre id="status"></pre><script src="data.js"></script><script>
const $=x=>document.getElementById(x);let current=0; $('tier').textContent='Evidence tier: '+DATA.evidence_tier+(DATA.evidence_tier==='mock'?' · FABRICATED FIXTURE, NOT REAL USER DATA':'');
DATA.videos.forEach((v,i)=>{let o=document.createElement('option');o.value=i;o.textContent=v.path;$('segments').append(o)});
function choose(){current=+$('segments').value;$('video').src=DATA.videos[current].path} $('segments').onchange=choose;
if(DATA.videos.length)choose();else{$('video').hidden=true;$('camera').hidden=false;$('slider').hidden=false;$('slider').max=Math.max(0,DATA.frames.length-1)}
function tick(){let ns;
if(DATA.legacy){let f=DATA.frames[+$('slider').value];if(!f){$('status').textContent='No mapped JPEG frames';requestAnimationFrame(tick);return} ns=BigInt(f.t);$('camera').src=f.path;$('camera').style.transform=`rotate(${f.rotation}deg)`}
else if(DATA.videos.length){let v=DATA.videos[current],rel=BigInt(Math.round($('video').currentTime*1e9));let a=v.anchors.filter(a=>BigInt(a.relative)<=rel).at(-1);if(a)ns=BigInt(a.elapsed)+rel-BigInt(a.relative)}
if(ns!==undefined){let trial=DATA.trials.find(t=>BigInt(t.onset)<=ns&&ns<=BigInt(t.offset));$('dot').hidden=true;
if(trial){let state=trial.ui.filter(u=>BigInt(u.t)<=ns).at(-1);if(state){$('ui').src=`session/trials/${trial.id}/${state.screenshot_path}`;let touches=trial.touch.filter(t=>BigInt(t.t)<=ns);let t=touches.at(-1);if(t&&t.x_px!==undefined&&ns-BigInt(t.t)<300000000n){$('dot').hidden=false;$('dot').style.left=(t.x_px/state.view_size_px[0]*$('ui').clientWidth-9)+'px';$('dot').style.top=(t.y_px/state.view_size_px[1]*$('ui').clientHeight-9)+'px'}$('status').textContent=trial.id+' · UI version '+(state.ui_state_version||0)+' · '+touches.slice(-5).map(t=>t.action).join(', ')}}
else{let page=(DATA.pages||[]).filter(p=>BigInt(p.t)<=ns).at(-1);if(page){$('ui').src='session/'+page.screenshot_path;$('status').textContent=page.page_id+' · estimated elapsed ns '+ns}else{$('ui').removeAttribute('src');$('status').textContent='问卷/说明/休息/暂停片段 · estimated elapsed ns '+ns}}}
requestAnimationFrame(tick)}tick();</script>'''
