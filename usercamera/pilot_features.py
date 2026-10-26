"""Offline timestamped CameraX frame-sequence features and causal windows."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation
from .io import read_jsonl,write_json,write_jsonl,sha256
from .pilot_session import session_folder,verify_folder,read_trial,safe_path,map_camera_frame

SCREEN_KEYS=['glyph_height_px','contrast_ratio','element_count','target_x','target_y','button_area_fraction','text_density']
ACTION_KEYS=['elapsed_s','clicks','downs','misclicks','help_requests','time_since_previous_action_s','max_touch_pause_s']
USER_KEYS=['face_detection_fraction','face_scale_mean','relative_inverse_scale_change','head_x_mean','head_y_mean',
    'yaw_mean_deg','pitch_mean_deg','roll_mean_deg','head_rotation_magnitude_deg','angular_velocity_deg_s','feature_stability',
    'camera_observed','camera_feature_missing_fraction','eye_in_frame_fraction_proxy','frame_quality_laplacian',
    'gaze_left_occupancy','gaze_center_occupancy','gaze_right_occupancy','gaze_available']


def create_mediapipe_task(factory,options):
    try:return factory.create_from_options(options)
    except RuntimeError as e:raise ValueError('MediaPipe initialization failed; check local model and OS graphics-context access even with CPU inference: '+str(e)) from e


class FaceLandmarkerBackend:
    def __init__(self,model,detector_model=None):
        try:import mediapipe as mp
        except ImportError as e:raise ValueError('MediaPipe is optional: install mobile_pilot/requirements-features.txt; no implicit install/download') from e
        if model is None or not Path(model).is_file():raise ValueError('Explicit local --model FaceLandmarker .task path required')
        self.mp=mp;self.last_ms=-1
        self.landmarker=create_mediapipe_task(mp.tasks.vision.FaceLandmarker,mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model),delegate=mp.tasks.BaseOptions.Delegate.CPU),running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_faces=1,output_facial_transformation_matrixes=True,min_face_detection_confidence=.5,min_face_presence_confidence=.5,min_tracking_confidence=.5))
        self.detector=None
        if detector_model:
            self.detector=create_mediapipe_task(mp.tasks.vision.FaceDetector,mp.tasks.vision.FaceDetectorOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(detector_model),delegate=mp.tasks.BaseOptions.Delegate.CPU),running_mode=mp.tasks.vision.RunningMode.VIDEO))
    def close(self):
        self.landmarker.close()
        if self.detector:self.detector.close()
    def extract(self,image,timestamp_ns):
        # MediaPipe requires strictly increasing integer milliseconds; reject sub-ms duplicates rather than inventing time.
        ms=int(timestamp_ns//1000000)
        if ms<=self.last_ms:raise ValueError('MediaPipe video timestamps must increase by at least one millisecond')
        self.last_ms=ms;rgb=np.asarray(image.convert('RGB'));mp_image=self.mp.Image(image_format=self.mp.ImageFormat.SRGB,data=rgb)
        result=self.landmarker.detect_for_video(mp_image,ms)
        gray=np.asarray(image.convert('L'),float);lap=4*gray[1:-1,1:-1]-gray[:-2,1:-1]-gray[2:,1:-1]-gray[1:-1,:-2]-gray[1:-1,2:]
        score=None
        if self.detector:
            detections=self.detector.detect_for_video(mp_image,ms).detections
            if detections:score=float(detections[0].categories[0].score)
        out={'face_present':bool(result.face_landmarks),'face_detection_confidence':score,
             'eye_landmark_visibility':None,'eye_in_frame_fraction_proxy':None,'gaze_region':None,'gaze_confidence':None,
             'gaze_unavailable_reason':'no independently validated screen-gaze mapping',
             'frame_quality_laplacian':float(lap.var()),'feature_source':'mediapipe_face_landmarker',
             'distance_kind':'relative_face_scale_proxy_not_absolute_mm',
             'visibility_note':'FaceLandmarker does not expose reliable per-eye visibility; in-frame fraction is a separate proxy',
             'confidence_note':'FaceLandmarker thresholds are not returned detection scores; score null unless separate FaceDetector supplied'}
        if result.face_landmarks:
            points=np.array([[p.x,p.y,p.z] for p in result.face_landmarks[0]])
            eyes=points[[33,133,159,145,362,263,386,374],:2]
            out.update(face_scale=float(np.ptp(points[:,0])),head_x=float(points[1,0]),head_y=float(points[1,1]),
                       eye_in_frame_fraction_proxy=float(((eyes>=0)&(eyes<=1)).all(1).mean()))
            if result.facial_transformation_matrixes:
                matrix=np.asarray(result.facial_transformation_matrixes[0]);u,_,vt=np.linalg.svd(matrix[:3,:3]);r=u@vt
                if np.linalg.det(r)<0:u[:,-1]*=-1;r=u@vt
                angles=Rotation.from_matrix(r).as_euler('yxz',degrees=True)
                out.update(yaw_deg=float(angles[0]),pitch_deg=float(angles[1]),roll_deg=float(angles[2]),
                    pose_convention='MediaPipe canonical-face transform; extrinsic yxz, degrees; not motion-capture truth')
        return out


def camera_summary(frames,start,cutoff):
    selected=[r for r in frames if start<=r['timestamp_ns']<=cutoff and r['available_ns']<=cutoff]
    face=[r for r in selected if r.get('face_present')]
    def average(key):
        vals=[r[key] for r in face if r.get(key) is not None and np.isfinite(r[key])]
        return float(np.mean(vals)) if vals else None
    scale=[r['face_scale'] for r in face if r.get('face_scale') is not None and r['face_scale']>0]
    poses=[r for r in face if all(r.get(k) is not None for k in ['yaw_deg','pitch_deg','roll_deg'])]
    velocity=[];rotation=None;stability=None
    if len(poses)>1:
        angles=np.array([[r['yaw_deg'],r['pitch_deg'],r['roll_deg']] for r in poses]);rot=Rotation.from_euler('yxz',angles,degrees=True)
        relative=np.degrees((rot[0].inv()*rot).magnitude());rotation=float(relative[-1]);stability=float(np.mean(np.std(np.unwrap(np.radians(angles),axis=0),axis=0)))
        dt=np.diff([r['timestamp_ns'] for r in poses])/1e9;step=np.degrees((rot[:-1].inv()*rot[1:]).magnitude())
        velocity=(step[(dt>0)&(dt<=.5)]/dt[(dt>0)&(dt<=.5)]).tolist()
    gaze=[r['gaze_region'] for r in face if r.get('gaze_region') in ['left','center','right'] and r.get('gaze_confidence',0) is not None and r.get('gaze_confidence',0)>=.8]
    out={'face_detection_fraction':len(face)/len(selected) if selected else None,
         'face_scale_mean':average('face_scale'),'relative_inverse_scale_change':scale[0]/scale[-1]-1 if scale else None,
         'head_x_mean':average('head_x'),'head_y_mean':average('head_y'),'yaw_mean_deg':average('yaw_deg'),
         'pitch_mean_deg':average('pitch_deg'),'roll_mean_deg':average('roll_deg'),
         'head_rotation_magnitude_deg':rotation,'angular_velocity_deg_s':float(np.mean(velocity)) if velocity else None,
         'feature_stability':stability,'camera_observed':int(bool(selected)),
         'camera_feature_missing_fraction':1-len(face)/len(selected) if selected else 1.,
         'eye_in_frame_fraction_proxy':average('eye_in_frame_fraction_proxy'),'frame_quality_laplacian':average('frame_quality_laplacian'),
         'gaze_available':int(bool(gaze))}
    for region in ['left','center','right']:out['gaze_'+region+'_occupancy']=gaze.count(region)/len(gaze) if gaze else None
    return out


def screen_summary(states,cutoff):
    known=[s for s in states if s['timestamp_ns']<=cutoff]
    if not known:raise ValueError('No causally available UI state')
    state=known[-1];els=state['elements'];w,h=state['view_size_px'];target=next(e for e in els if e['element_id']==state['target_element_id'])
    box=target['bounding_box_px'];click=target['clickable_region_px']
    return {'glyph_height_px':float(np.median([e.get('actual_glyph_height_px',e['font_glyph_height_px']) for e in els])),
        'contrast_ratio':float(np.median([e['visual_contrast'] for e in els])),'element_count':len(els),
        'target_x':(box[0]+box[2])/2/w,'target_y':(box[1]+box[3])/2/h,
        'button_area_fraction':(click[2]-click[0])*(click[3]-click[1])/(w*h),
        'text_density':sum(len(e['text']) for e in els)/(w*h/1e6)}


def action_summary(events,start,cutoff):
    events=[a for a in events if start<=a['timestamp_ns']<=cutoff]
    times=sorted(set([start]+[a['timestamp_ns'] for a in events]+[cutoff]));ups=[a for a in events if a['action']=='up']
    return {'elapsed_s':(cutoff-start)/1e9,'clicks':len(ups),'downs':sum(a['action']=='down' for a in events),
        'misclicks':sum(not a.get('correct_target_hit',False) for a in ups),'help_requests':sum(a['action']=='help_request' for a in events),
        'time_since_previous_action_s':(cutoff-max([start]+[a['timestamp_ns'] for a in events]))/1e9,
        'max_touch_pause_s':max(np.diff(times),default=0)/1e9}


def causal_window(trial,frames,cutoff):
    start=trial['meta']['onset_ns']
    if not start<cutoff<=trial['meta']['offset_ns']:raise ValueError('Causal cutoff outside observed trial')
    return {'screen':screen_summary(trial['ui'],cutoff),'actions':action_summary(trial['touch'],start,cutoff),
            'user':camera_summary(frames,start,cutoff)}


def extract_features(path,output='reports/pilot',backend='mediapipe',model=None,detector_model=None,allow_mock=False,allow_estimated_clock=False):
    with session_folder(path) as root:
        quality=verify_folder(root,allow_mock,allow_estimated_clock);s=json.loads((root/'session.json').read_text())
        if backend=='mock' and (not allow_mock or s['evidence_tier']!='mock'):raise ValueError('Fabricated observations only permitted in explicitly allowed mock sessions')
        extractor=FaceLandmarkerBackend(model,detector_model) if backend=='mediapipe' else None
        if backend not in ['mock','mediapipe']:raise ValueError('Unknown feature backend')
        dest=Path(output)/'features'/s['session_id'];frame_rows=[];windows=[];excluded=[]
        try:
            for trial_id in s['trial_ids']:
                folder=root/'trials'/trial_id;t=read_trial(folder);m=t['meta'];f=t['feedback'];frames=[]
                mock={r['frame_id']:r for r in read_jsonl(folder/'mock_camera_observations.jsonl')} if backend=='mock' else {}
                for raw in t['camera']:
                    if raw['status']!='recorded':continue
                    timestamp,bound,clock_status=map_camera_frame(raw,allow_estimated_clock)
                    if timestamp is None:continue
                    if backend=='mock':observation=mock[raw['frame_id']]
                    else:
                        try:
                            with Image.open(safe_path(folder,raw['path'])) as image:
                                observation=extractor.extract(image.rotate(-raw.get('rotation_degrees',0),expand=True),timestamp)
                        except (RuntimeError,ValueError,np.linalg.LinAlgError) as e:
                            observation={'face_present':False,'face_detection_confidence':None,'eye_landmark_visibility':None,
                                'gaze_region':None,'gaze_confidence':None,'feature_source':'mediapipe_frame_failure',
                                'feature_error':type(e).__name__+':'+str(e)}
                    row={**observation,'trial_id':trial_id,'frame_id':raw['frame_id'],'timestamp_ns':timestamp,
                         'available_ns':max(raw['arrival_elapsed_ns'],raw.get('stored_elapsed_ns',raw['arrival_elapsed_ns'])),
                         'clock_status':clock_status,'sync_uncertainty_ns':bound,'evidence_tier':s['evidence_tier']}
                    frames.append(row);frame_rows.append(row)
                if m['task']!='visual_search' or m['status'].startswith('aborted') or f.get('status')!='provided':
                    excluded.append({'trial_id':trial_id,'reason':'calibration_or_aborted_or_missing_self_report'});continue
                for mode,prefix in [('trial',None),('prefix_1s',1),('prefix_2s',2),('prefix_3s',3)]:
                    cutoff=m['offset_ns'] if prefix is None else m['onset_ns']+int(prefix*1e9)
                    if cutoff>m['offset_ns']:
                        excluded.append({'trial_id':trial_id,'mode':mode,'reason':'trial_completed_before_fixed_prefix; selection may favor longer trials'});continue
                    feature=causal_window(t,frames,cutoff)
                    # Equal relative-time bins for GRU; each step is itself causal, with no interpolation from later observations.
                    steps=[causal_window(t,frames,m['onset_ns']+(cutoff-m['onset_ns'])*j//6) for j in range(1,7)]
                    windows.append({'schema_version':'pilot-window-v2','id':s['session_id']+':'+trial_id+':'+mode,
                        'participant_id':s['participant_id'],'subject_id':s['participant_id'],'session_id':s['session_id'],
                        'trial_id':trial_id,'template_id':m['template_id'],'mode':mode,'evidence_tier':s['evidence_tier'],
                        'input_start_ns':m['onset_ns'],'input_end_ns':cutoff,'label_time_ns':f['timestamp_ns'],
                        'label_resolution':'trial_only','difficulty':int(f['difficulty_rating']>=3),'difficulty_rating':f['difficulty_rating'],
                        'difficulty_label_source':f['label_source'],'difficulty_type':f['difficulty_type'],
                        'clock_alignment_usable':quality['clock_alignment_usable'],**feature,'sequence':steps})
        finally:
            if extractor:extractor.close()
        write_jsonl(dest/'camera_features.jsonl',frame_rows);write_jsonl(dest/'windows.jsonl',windows)
        report={'session_id':s['session_id'],'evidence_tier':s['evidence_tier'],'backend':backend,'frames':len(frame_rows),'windows':len(windows),
            'feature_failure_frames':sum('feature_error' in r for r in frame_rows),
            'model_sha256':sha256(model) if backend=='mediapipe' and model else None,'quality':quality,'excluded_windows':excluded,
            'distance':'relative inverse face scale; absolute distance is not measured','gaze':'unavailable unless separately validated gaze confidence >=.8',
            'label_resolution':'post-trial self report; not frame-level difficulty onset','input_source':str(path),
            'online_scope':'fixed-prefix replay of observations available by cutoff; offline feature-compute latency is not an online runtime measurement'}
        write_json(dest/'extraction.json',report);return report
