"""Local-only face proxies for audit/compression; no gaze or metric-distance truth."""
import time
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from .pilot_features import create_mediapipe_task


class AuditFaceBackend:
    def __init__(self,model='data/models/face_landmarker.task'):
        import mediapipe as mp
        if not Path(model).is_file():raise ValueError('Use existing local FaceLandmarker model; no implicit download')
        self.mp=mp;self.last_ms=-1
        self.task=create_mediapipe_task(mp.tasks.vision.FaceLandmarker,mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model),delegate=mp.tasks.BaseOptions.Delegate.CPU),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,num_faces=2,output_facial_transformation_matrixes=True,
            output_face_blendshapes=True,min_face_detection_confidence=.5,min_face_presence_confidence=.5))
    def close(self):self.task.close()
    def extract(self,image,pts_us):
        ms=int(pts_us//1000)
        if ms<=self.last_ms:raise ValueError('Non-increasing audit frame time')
        self.last_ms=ms;start=time.perf_counter()
        result=self.task.detect_for_video(self.mp.Image(image_format=self.mp.ImageFormat.SRGB,data=np.asarray(image.convert('RGB'))),ms)
        out={'face_present':bool(result.face_landmarks),'face_count':len(result.face_landmarks),
            'inference_ms':(time.perf_counter()-start)*1000,'confidence':None,'eye_landmark_visibility':None,
            'pose_kind':'canonical_face_yxz_proxy','distance_kind':'relative_face_scale_not_mm'}
        if not result.face_landmarks:return out
        points=np.array([[p.x,p.y,p.z] for p in result.face_landmarks[0]])
        x0,y0=points[:,:2].min(0);x1,y1=points[:,:2].max(0);eyes=points[[33,133,159,145,362,263,386,374],:2]
        out.update(face_box_normalized=[float(x0),float(y0),float(x1),float(y1)],face_area_fraction=float((x1-x0)*(y1-y0)),
            face_scale=float(x1-x0),head_x=float(points[1,0]),head_y=float(points[1,1]),
            eye_in_frame_fraction_proxy=float(((eyes>=0)&(eyes<=1)).all(1).mean()),
            face_fully_in_frame_proxy=bool(x0>.02 and y0>.02 and x1<.98 and y1<.98),
            edge_truncation_proxy=bool(x0<0 or y0<0 or x1>1 or y1>1),
            edge_margin_normalized=float(min(x0,y0,1-x1,1-y1)),eye_points_normalized=eyes.tolist())
        if result.facial_transformation_matrixes:
            m=np.asarray(result.facial_transformation_matrixes[0]);u,_,v=np.linalg.svd(m[:3,:3]);r=u@v
            if np.linalg.det(r)<0:u[:,-1]*=-1;r=u@v
            angles=Rotation.from_matrix(r).as_euler('yxz',degrees=True)
            out.update(yaw_deg=float(angles[0]),pitch_deg=float(angles[1]),roll_deg=float(angles[2]),rotation_matrix=r.tolist())
        if result.face_blendshapes:
            for value in result.face_blendshapes[0]:
                if value.category_name in ['eyeBlinkLeft','eyeBlinkRight']:out[value.category_name]=float(value.score)
        return out
