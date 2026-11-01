"""Same-source compression derivatives; original PTS and raw video are never overwritten."""
import json,time,hashlib
from pathlib import Path
from fractions import Fraction
import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation
from .pilot_v3_audit import describe,csv_write
from .pilot_v3_faces import AuditFaceBackend
from .io import write_json,write_jsonl,sha256


def encode_variants(source,destination,configs):
    import av
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True);writers=[]
    for name,width,height,mbps in configs:
        p=destination/(name+'.mp4')
        if p.exists():raise ValueError('Derived video exists; no overwrite: '+str(p))
        container=av.open(str(p),'w');stream=container.add_stream('libx264',rate=30);stream.width=width;stream.height=height;stream.pix_fmt='yuv420p';stream.bit_rate=int(mbps*1e6)
        stream.codec_context.time_base=Fraction(1,1000000);stream.codec_context.max_b_frames=0;stream.codec_context.thread_count=1
        stream.options={'preset':'veryfast','x264-params':f'vbv-maxrate={int(mbps*1000)}:vbv-bufsize={int(mbps*2000)}:force-cfr=0'}
        writers.append((name,p,container,stream))
    start=time.perf_counter();n=0
    try:
        with av.open(str(source)) as input:
            for frame in input.decode(video=0):
                pts_us=int(frame.pts*frame.time_base*1000000)
                for name,p,c,s in writers:
                    resized=frame.reformat(s.width,s.height,format='yuv420p');resized.pts=pts_us;resized.time_base=Fraction(1,1000000)
                    for packet in s.encode(resized):c.mux(packet)
                n+=1
        for name,p,c,s in writers:
            for packet in s.encode():c.mux(packet)
    finally:
        for _,_,c,_ in writers:c.close()
    return {'frames':n,'encoding_total_s':time.perf_counter()-start,'variants':[str(p) for _,p,_,_ in writers]}


def compression_experiment(session='test1030_20261030_144219',output='reports/pilot_v3/compression',derived='data/derivatives/pilot_v3/test1030_20261030_144219'):
    import av
    root=Path(session);source=root/'front_camera.mp4';before=sha256(source)
    expected=json.loads(Path('reports/pilot_v3/audit_20261030/preservation.json').read_text())['source_sha256']['front_camera.mp4']
    if before!=expected:raise ValueError('Compression reference belongs to another original; supply a matching audit before reusing frame IDs')
    out=Path(output)
    if (out/'results.json').exists():raise ValueError('Compression results exist; choose a new output')
    out.mkdir(parents=True,exist_ok=True)
    priv=Path('reports/pilot_v3/private/compression');priv.mkdir(parents=True,exist_ok=True)
    reference=[json.loads(x) for x in Path('reports/pilot_v3/private/audit_20261030/offline_face_observations.jsonl').read_text().splitlines()];wanted={r['frame_index']:r for r in reference}
    configs=[(f'h264_{width}w_{rate}mbps',width,height,rate) for width,height in [(720,1280),(480,854)] for rate in [1,2,4]]
    encoded=encode_variants(source,derived,configs);write_json(out/'encoding.json',encoded)
    allpts=[];original_images={};crops=Path(derived)/'face_crops';crops.mkdir()
    with av.open(str(source)) as c:
        for i,f in enumerate(c.decode(video=0)):
            allpts.append(int(f.pts*f.time_base*1000000))
            if i in wanted:
                im=f.to_image();original_images[i]=im
                box=wanted[i].get('face_box_normalized')
                if box:
                    a,b,x,y=box;roi=(max(0,int(a*im.width)),max(0,int(b*im.height)),min(im.width,int(x*im.width)),min(im.height,int(y*im.height)))
                    if roi[2]>roi[0] and roi[3]>roi[1]:im.crop(roi).resize((192,192)).save(crops/f'{i:06d}.jpg',quality=90)
    write_jsonl(Path(derived)/'compact_features.jsonl',[{k:v for k,v in r.items() if k not in ['eye_points_normalized','rotation_matrix']} for r in reference])
    rows=[];perframe=[]
    for name,width,height,rate in [('original',720,1280,None)]+configs:
        path=source if name=='original' else Path(derived)/(name+'.mp4');backend=AuditFaceBackend();decoded_pts=[];observations=[];start=time.perf_counter()
        try:
            with av.open(str(path)) as container:
                duration=container.duration/1e6;codec=container.streams.video[0].codec_context.name
                for i,frame in enumerate(container.decode(video=0)):
                    pts=int(frame.pts*frame.time_base*1000000);decoded_pts.append(pts)
                    if i not in wanted:continue
                    image=frame.to_image();ref=wanted[i]
                    try:obs=backend.extract(image,pts)
                    except Exception as e:obs={'face_present':False,'error':str(e)}
                    pose=None;eyes=None
                    if obs.get('rotation_matrix') is not None and ref.get('rotation_matrix') is not None:
                        pose=float(np.degrees((Rotation.from_matrix(np.array(ref['rotation_matrix'])).inv()*Rotation.from_matrix(np.array(obs['rotation_matrix']))).magnitude()))
                    if obs.get('eye_points_normalized') is not None and ref.get('eye_points_normalized') is not None:
                        eyes=float(np.mean(np.linalg.norm(np.array(obs['eye_points_normalized'])-np.array(ref['eye_points_normalized']),axis=1)))
                    # Eye image error uses reference ROI and includes frames even when variant detector fails.
                    original=np.asarray(original_images[i],float);decoded=np.asarray(image.resize(original_images[i].size),float);eye_mse=[]
                    if ref.get('eye_points_normalized'):
                        for x,y in np.array(ref['eye_points_normalized'])[[0,4]]:
                            cx=int(x*original.shape[1]);cy=int(y*original.shape[0]);a=max(0,cx-32);b=max(0,cy-20);c=min(original.shape[1],cx+32);d=min(original.shape[0],cy+20)
                            if c>a and d>b:eye_mse.append(float(np.mean((original[b:d,a:c]-decoded[b:d,a:c])**2)))
                    mse=float(np.mean(eye_mse)) if eye_mse else None
                    value={'variant':name,'frame_index':i,'pts_us':pts,'reference_face':ref.get('face_present',False),'face_present':obs.get('face_present',False),
                        'eyes_in_frame':obs.get('eye_in_frame_fraction_proxy')==1,'strict_full_face':obs.get('face_fully_in_frame_proxy',False),
                        'pose_proxy_difference_deg':pose,'eye_landmark_normalized_difference':eyes,
                        'eye_roi_psnr_db':float(10*np.log10(255**2/mse)) if mse is not None and mse>0 else None,
                        'eye_roi_mse':mse,'face_scale':obs.get('face_scale'),'yaw_deg':obs.get('yaw_deg'),'pitch_deg':obs.get('pitch_deg'),'roll_deg':obs.get('roll_deg')}
                    observations.append(value)
        finally:backend.close()
        inference_decode_s=time.perf_counter()-start
        start=time.perf_counter()
        with av.open(str(path)) as c:
            count=sum(1 for _ in c.decode(video=0))
        decode_s=time.perf_counter()-start
        if decoded_pts!=allpts:raise ValueError('Compression changed frame PTS/count: '+name)
        ypr=np.array([[r.get(k) if r.get(k) is not None else np.nan for k in ['yaw_deg','pitch_deg','roll_deg']] for r in observations])
        row={'variant':name,'path':str(path),'target_mbps':rate,'actual_mbps':path.stat().st_size*8/duration/1e6,'bytes':path.stat().st_size,'MiB':path.stat().st_size/2**20,
             'codec':codec,'width':width,'height':height,'duration_s':duration,'frames':count,'PTS_identical_to_original':True,
             'decode_s':decode_s,'decode_fps':count/decode_s,'same_sample_n':len(observations),
             'face_detection_ratio':float(np.mean([r['face_present'] for r in observations])),
             'eyes_in_frame_proxy_ratio':float(np.mean([r['eyes_in_frame'] for r in observations])),
             'strict_full_face_proxy_ratio':float(np.mean([r['strict_full_face'] for r in observations])),
             'head_pose_difference_conditional':describe([r['pose_proxy_difference_deg'] for r in observations]),
             'eye_landmark_difference_conditional':describe([r['eye_landmark_normalized_difference'] for r in observations]),
             'eye_roi_psnr_db':describe([r['eye_roi_psnr_db'] for r in observations]),'pose_std_deg':[float(v) for v in np.nanstd(ypr,axis=0)],
             'sampled_stability_note':'std over same sparse real timestamps; not validated blink/dwell dynamics',
             'detection_failures_included_in_denominator':True,'pose_error_is_model_consistency_not_true_accuracy':True,
             'decode_and_sampled_inference_s':inference_decode_s,'sha256':sha256(path)}
        rows.append(row);perframe.extend(observations);write_json(out/'results_partial.json',rows)
        print(name,row['MiB'],row['face_detection_ratio'],flush=True)
    csv_write(out/'compression_quality.csv',rows);write_json(out/'results.json',rows);write_jsonl(priv/'same_frames_quality.jsonl',perframe)
    crop_bytes=sum(p.stat().st_size for p in crops.glob('*.jpg'));compact=Path(derived)/'compact_features.jsonl'
    feature_cost={'face_crops':len(list(crops.glob('*.jpg'))),'crop_bytes':crop_bytes,'feature_bytes':compact.stat().st_size,
        'sampled_not_full_video':True,'face_crops_have_reference_detector_selection_bias':True,'per_missing_frame_mask_required':True}
    write_json(out/'compact_cost.json',feature_cost)
    report=['# Same-source compression experiment','', '所有6份派生视频保留全部原始5173个PTS；原始视频未覆盖。1/2/4Mbps是编码目标，实际码率见表。人脸/眼指标是同一117帧的模型一致性，非人类gaze/眼部准确度。Conditional pose/landmark error同时给出有效n和全体检测失败率，不隐藏失败样本。', '',
        '| Variant | MiB | Actual Mbps | Face ratio | Eyes in-frame proxy | Pose diff mean (deg, conditional) | Eye PSNR mean |','|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:report.append(f'|{r["variant"]}|{r["MiB"]:.2f}|{r["actual_mbps"]:.2f}|{r["face_detection_ratio"]:.3f}|{r["eyes_in_frame_proxy_ratio"]:.3f}|{r["head_pose_difference_conditional"]["mean"]}|{r["eye_roi_psnr_db"]["mean"]}|')
    report+=['','Eye in-frame不是可靠visibility，更不是精细眼动保真。即使检测率不降，低码率仍可能丢失瞳孔/眼睑细节；不能仅凭此推荐最小文件配置用于gaze研究。原件保留作calibration quality；normal交互可候选720p 2/4Mbps进一步核验；480p/1Mbps作为debug轻量候选，不宣称与原始眼部细节等价。', '',
        f'仅此117帧192×192裁剪 {crop_bytes/2**20:.3f}MiB；compact proxies {compact.stat().st_size}bytes，不能把稀疏样本成本冒充整段完整特征成本。训练优先一次提取并缓存，再按真实PTS/缺失掩码切窗，避免每epoch重解码原视频。', '',
        '本轮没有把这些码率写死为设备必达值。未来APK可提供calibration/normal/debug模式；先以同源实验选候选，再在设备分别测FPS和眼部质量，不能把桌面转码结果当CameraX设备实测。', '',
        '反馈/长休息可选暂停视频以节省存储，但必须记录phase、Pause/Resume与缺失区间；任务连续段和校准段应保留；若研究需要跨任务状态，暂停会截断其可观测性。']
    (out/'compression_report.md').write_text('\n'.join(report)+'\n')
    assert sha256(source)==before
    write_json(out/'preservation.json',{'original_sha256':before,'unchanged':True,'derived_files_never_overwrite_raw':True})
    return rows

if __name__=='__main__':compression_experiment()
