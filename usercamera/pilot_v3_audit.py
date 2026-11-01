"""Read-only audit of a real v2/v3 export. Raw faces only in a separate private folder."""
import csv,json,hashlib,html,time
from pathlib import Path
from collections import Counter
import numpy as np
from PIL import Image,ImageDraw,ImageOps
from .io import read_jsonl,write_json,write_jsonl,sha256
from .pilot_video import estimate_elapsed,mapping_anchors,touch_coordinates_valid,touch_clock_valid


def csv_write(path,rows):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()} for r in rows)


def describe(values):
    a=np.asarray([v for v in values if v is not None and np.isfinite(v)],float)
    return {'n':len(a),'mean':float(a.mean()) if len(a) else None,'p05':float(np.quantile(a,.05)) if len(a) else None,
            'median':float(np.median(a)) if len(a) else None,'p95':float(np.quantile(a,.95)) if len(a) else None,'max':float(a.max()) if len(a) else None}


def fps_stats(pts_us,indices=None):
    pts=np.asarray(pts_us,dtype=np.int64);idx=np.arange(len(pts)) if indices is None else np.asarray(indices,int)
    if not len(idx):return {'frames':0,'effective_pts_fps':None,'within_period_effective_fps':None,'instant_fps':describe([]),'gaps_over_75ms':0,'duplicates':0}
    selected=pts[idx];d=np.diff(selected);adj=np.diff(idx)==1;local=d[adj]
    return {'frames':len(idx),'effective_pts_fps':float((len(idx)-1)*1e6/(selected[-1]-selected[0])) if len(idx)>1 and selected[-1]>selected[0] else None,
        'within_period_effective_fps':float((local>0).sum()*1e6/local[local>0].sum()) if (local>0).any() else None,
        'instant_fps':describe(1e6/local[local>0]),'gaps_over_75ms':int((local>75000).sum()),'duplicates':int((local==0).sum()),
        'max_pts_gap_us':int(local.max()) if len(local) else None,'disjoint_category_note':'effective_pts_fps over disjoint spans is sampling density; use instant_fps for local recording rate'}


def audit_session(path='test1030_20261030_144219',output='reports/pilot_v3/audit_20261030',private='reports/pilot_v3/private/audit_20261030',offline_samples=96):
    import av
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    root=Path(path);out=Path(output);priv=Path(private)
    if out.exists() and any(out.iterdir()):raise ValueError('Audit output exists; preserve results and select a new output')
    out.mkdir(parents=True,exist_ok=True);priv.mkdir(parents=True,exist_ok=True);(out/'figures').mkdir(exist_ok=True)
    session=json.loads((root/'session.json').read_text());manifest=json.loads((root/'export_manifest.json').read_text())
    original={p.relative_to(root).as_posix():sha256(p) for p in root.rglob('*') if p.is_file()}
    declared={r['path']:r for r in manifest['files']};extra=sorted(set(original)-set(declared)-{'export_manifest.json'})
    bad=[p for p,r in declared.items() if p not in original or original[p]!=r['sha256'] or (root/p).stat().st_size!=r['bytes']]
    if bad:raise ValueError('Raw export corruption: '+str(bad))
    timeline=read_jsonl(root/'video_timeline.jsonl');live=read_jsonl(root/'live_face_features.jsonl');touch=read_jsonl(root/'touch_events.jsonl');assist=read_jsonl(root/'assistance_events.jsonl');events=read_jsonl(root/'session_events.jsonl');states=read_jsonl(root/'ui_states.jsonl')
    pngs=[]
    for p in sorted(root.rglob('*.png')):
        with Image.open(p) as im:im.load();pngs.append({'path':p.relative_to(root).as_posix(),'width':im.width,'height':im.height,'bytes':p.stat().st_size})
    write_json(out/'png_integrity.json',{'checked':len(pngs),'files':pngs})
    trials=[];trial_data={}
    for tid in session['trial_ids']:
        d=root/'trials'/tid;meta=json.loads((d/'trial_meta.json').read_text());feedback=json.loads((d/'feedback.json').read_text());ui=read_jsonl(d/'ui_states.jsonl');te=read_jsonl(d/'touch_events.jsonl')
        target=next(e for e in meta['stimulus']['elements'] if e['element_id']==meta['stimulus']['target_element_id']);actual=next(e for e in ui[0]['elements'] if e['element_id']==ui[0]['target_element_id']);b=actual['bounding_box_px'];w,h=ui[0]['view_size_px']
        trial_data[tid]={'meta':meta,'ui':ui,'touch':te,'feedback':feedback}
        trials.append({'trial_id':tid,'task':meta['task'],'target_text':target['text'],'target_element_id':target['element_id'],
            'target_x_norm':(b[0]+b[2])/2/w,'target_y_norm':(b[1]+b[3])/2/h,'element_count':len(ui[0]['elements']),
            'font_glyph_height_px':actual.get('actual_glyph_height_px'),'contrast':actual.get('visual_contrast'),
            'foreground_gray':actual.get('foreground_gray'),'background_argb':actual.get('rendered_background_argb','legacy_white_except_highlight'),
            'onset_ns':meta['onset_ns'],'offset_ns':meta['offset_ns'],'duration_s':(meta['offset_ns']-meta['onset_ns'])/1e9,
            'status':meta['status'],'pair_id':meta.get('pair_id'),'matched_factor':meta['stimulus'].get('matched_factor'),
            'assigned_assistance':meta['stimulus'].get('initial_assistance','none'),'help_requests':sum(t['action']=='help_request' for t in te),
            'actual_touch_up':sum(t['action']=='up' for t in te),'misclicks':meta['outcome']['misclicks'],'success':meta['outcome']['success'],
            'difficulty_rating':feedback.get('difficulty_rating'),'difficulty_reasons':feedback.get('difficulty_types'),
            'helpfulness':feedback.get('helpfulness_rating'),'preferred_assistance':feedback.get('preferred_assistance'),
            'feedback_source':feedback.get('label_source'),'feedback_status':feedback.get('status'),
            'touch_coordinate_checks_ok':all(touch_coordinates_valid(t) and touch_clock_valid(t) for t in te),
            'strict_fusion_eligible':False,'fusion_exclusion_reason':'no independent video PTS/exposure↔elapsed mapping'})
    video=root/'front_camera.mp4';anchors=mapping_anchors(timeline,video.name);pts=[];packet_sizes={}
    with av.open(str(video)) as container:
        stream=container.streams.video[0];codec=stream.codec_context.name;resolution=[stream.width,stream.height];duration=container.duration/1e6
        for packet in container.demux(stream):
            if packet.pts is not None:packet_sizes[int(packet.pts*packet.time_base*1000000)]=packet.size
    start_decode=time.perf_counter()
    with av.open(str(video)) as container:
        for frame in container.decode(video=0):pts.append(int(frame.pts*frame.time_base*1000000))
    decode_s=time.perf_counter()-start_decode
    encoded=[r['pts_us'] for r in timeline if r['type']=='encoded_frame' and r['path']==video.name]
    if pts!=encoded:raise ValueError('MP4 decode PTS != stored encoded timeline')
    mapped=np.array([estimate_elapsed(p,pts[0],anchors) for p in pts],dtype=np.int64)
    def phase(t):
        for r in trials:
            if r['onset_ns']<=t<=r['offset_ns']:return r['task']
        known=[e for e in events if e['timestamp_ns']<=t and e['type']=='ui_phase']
        return known[-1]['detail'] if known else 'quality_or_startup'
    phases=[phase(t) for t in mapped];phase_stats={};packet_bytes=np.array([packet_sizes.get(p,0) for p in pts],dtype=np.int64)
    # Attribute each encoded frame interval to its left-frame phase; inferred synchronization only.
    dt=np.r_[np.diff(pts)/1e6,np.median(np.diff(pts))/1e6]
    for name in sorted(set(phases)):
        idx=np.flatnonzero(np.array(phases)==name);phase_stats[name]={**fps_stats(pts,idx),'estimated_duration_s':float(dt[idx].sum()),'encoded_payload_bytes':int(packet_bytes[idx].sum())}
    intervals=[]
    for r in assist:
        if r['type']=='intervention_onset':intervals.append([r['timestamp_ns'],None,r['trial_id'],r['delivered_action']])
        elif r['type']=='intervention_end':
            matches=[i for i in intervals if i[1] is None and i[2]==r['trial_id'] and i[3]==r['delivered_action']]
            if matches:matches[-1][1]=r['timestamp_ns']
    ai=[i for i,t in enumerate(mapped) if any(a<=t<=(b if b is not None else t) for a,b,_,_ in intervals)]
    phase_stats['assistance_subset']={**fps_stats(pts,ai),'estimated_duration_s':float(dt[ai].sum()),'encoded_payload_bytes':int(packet_bytes[ai].sum())}
    for row in trials:
        idx=np.flatnonzero((mapped>=row['onset_ns'])&(mapped<=row['offset_ns']));selected=[f for f in live if f.get('timestamp_ns') is not None and row['onset_ns']<=f['timestamp_ns']<=row['offset_ns']]
        row.update(fps_stats(pts,idx));row.update(estimated_video_payload_bytes=int(packet_bytes[idx].sum()),live_frames=len(selected),live_face_frames=sum(bool(f.get('face_present')) for f in selected),
            live_result_fps=len(selected)/row['duration_s'],strict_full_face_ratio=float(np.mean([bool(f.get('face_fully_in_frame_proxy')) for f in selected])) if selected else None,
            eyes_in_frame_ratio=float(np.mean([f.get('eye_in_frame_fraction_proxy')==1 for f in selected])) if selected else None,
            face_success_ratio=float(np.mean([bool(f.get('face_present')) for f in selected])) if selected else None)
        row['has_camera_features']=bool(row['live_face_frames'])
        row['image_analysis_frames']=sum(f['type']=='analysis_sensor_frame' and f.get('mapped_timestamp_ns') is not None and row['onset_ns']<=f['mapped_timestamp_ns']<=row['offset_ns'] for f in timeline)
        row['image_analysis_fps']=row['image_analysis_frames']/row['duration_s']
        row['successful_face_fps']=row['live_face_frames']/row['duration_s']
    status=[r for r in timeline if r['type']=='status'];offsets=[r['timestamp_ns']-r['recorded_duration_ns'] for r in status]
    summary={'session_id':session['session_id'],'codec':codec,'encoded_resolution':resolution,'container_duration_s':duration,
        'video_bytes':video.stat().st_size,'video_MB':video.stat().st_size/1e6,'video_MiB':video.stat().st_size/2**20,
        'actual_bitrate_mbps':video.stat().st_size*8/duration/1e6,'whole_session':fps_stats(pts),'phases':phase_stats,
        'decode_s':decode_s,'decode_frames_per_s':len(pts)/decode_s,'pts_timeline_matches':True,
        'orientation_metadata':next(r for r in timeline if r['type']=='file_summary').get('rotation_degrees'),
        'mirroring':'raw false / preview true per metadata; physical mirror orientation not independently measured',
        'recorder_events':[r for r in timeline if r['type'] in ['start','pause','resume','finalize']],
        'sensor_analysis_frames':sum(r['type']=='analysis_sensor_frame' for r in timeline),'live_inference_frames':len(live),
        'live_face_frames':sum(bool(r.get('face_present')) for r in live),'analysis_fps':sum(r['type']=='analysis_sensor_frame' for r in timeline)/duration,
        'successful_face_fps':sum(bool(r.get('face_present')) for r in live)/duration,'inference_result_fps':len(live)/duration,
        'face_detection_success_ratio':float(np.mean([bool(r.get('face_present')) for r in live])) if live else None,
        'both_eyes_in_frame_proxy_ratio':float(np.mean([r.get('eye_in_frame_fraction_proxy')==1 for r in live])) if live else None,
        'strict_full_face_proxy_ratio':float(np.mean([bool(r.get('face_fully_in_frame_proxy')) for r in live])) if live else None,
        'inference_latency_ms':describe([r.get('inference_latency_ns',0)/1e6 for r in live]),
        'capture_to_available_ms':describe([(r['available_ns']-r['timestamp_ns'])/1e6 for r in live if r.get('timestamp_ns') is not None]),
        'eye_blink_feature_ratio':float(np.mean(['eyeBlinkLeft' in r and 'eyeBlinkRight' in r for r in live])) if live else None,
        'recorder_offset_spread_ms':(max(offsets)-min(offsets))/1e6 if offsets else None,
        'physical_sync_status':'unverified','physical_sync_uncertainty_ms':None,'manifest_verified':len(declared),'unmanifested_files':extra}
    write_json(out/'video_stats.json',summary)
    face_rows=[{'timestamp_ns':r.get('timestamp_ns'),'available_ns':r['available_ns'],'face_present':r.get('face_present'),
        'eyes_in_frame_proxy':r.get('eye_in_frame_fraction_proxy'),'strict_full_face_proxy':r.get('face_fully_in_frame_proxy'),
        'yaw_proxy_deg':r.get('yaw_proxy_deg'),'pitch_proxy_deg':r.get('pitch_proxy_deg'),'roll_proxy_deg':r.get('roll_proxy_deg'),
        'face_scale':r.get('face_scale'),'head_x':r.get('head_x'),'head_y':r.get('head_y'),
        'blink_left':r.get('eyeBlinkLeft'),'blink_right':r.get('eyeBlinkRight'),'inference_ms':r['inference_latency_ns']/1e6} for r in live]
    # Per-frame biometric proxies stay private; public CSV is trial-aggregated quality only.
    csv_write(priv/'live_face_frames.csv',face_rows);csv_write(out/'face_quality.csv',[{k:r[k] for k in ['trial_id','task','duration_s','live_frames','live_result_fps','image_analysis_fps','successful_face_fps','live_face_frames','face_success_ratio','eyes_in_frame_ratio','strict_full_face_ratio','has_camera_features']} for r in trials])
    csv_write(out/'trial_quality.csv',trials);csv_write(out/'target_distribution.csv',[{k:r[k] for k in ['trial_id','task','target_text','target_x_norm','target_y_norm','pair_id','matched_factor','assigned_assistance']} for r in trials])
    assistance=[]
    for a,b,tid,action in intervals:
        trial=trial_data[tid];ui=[s for s in trial['ui'] if s['timestamp_ns']>=a and s.get('delivered_assistance')==action]
        helps=[r['timestamp_ns'] for r in trial['touch'] if r['action']=='help_request'];source='assigned_pre_task_estimate' if not helps or a<min(helps) else 'self_selected_after_help_estimate'
        assistance.append({'trial_id':tid,'delivered_action':action,'intervention_onset_ns':a,'intervention_end_ns':b,'source_inferred':source,
            'source_is_explicit':False,'requested_equals_delivered':True,'post_ui_observed':bool(ui),'post_ui_version':ui[0]['ui_state_version'] if ui else None,
            'post_screenshot_exists':bool(ui and (root/'trials'/tid/ui[0]['screenshot_path']).exists()),'requested_vs_assignment_limit':'v2 uses same event fields; inferred temporal classification only'})
    csv_write(out/'assistance_summary.csv',assistance)
    # Pair matching compares actual planned elements; old descriptions are not accepted as proof.
    pairs=[]
    for pair in sorted({r.get('pair_id') for r in trials if r.get('pair_id')}):
        members=[r for r in trials if r.get('pair_id')==pair]
        if len(members)>=2:
            aa=trial_data[members[0]['trial_id']]['meta']['stimulus']['elements'];bb=trial_data[members[1]['trial_id']]['meta']['stimulus']['elements']
            changed=sorted({k for a,b in zip(aa,bb) for k in set(a)|set(b) if a.get(k)!=b.get(k)})
            pairs.append({'pair_id':pair,'trials':[r['trial_id'] for r in members],'element_fields_changed':changed})
    write_json(out/'pair_audit.json',pairs)
    # Offline sample choices are reproducible and include Live full-face success/failure strata when available.
    sample_idx=set(np.linspace(0,len(pts)-1,min(offline_samples,len(pts))).astype(int).tolist())
    for key in ['face_present','face_fully_in_frame_proxy']:
        for flag in [False,True]:
            subset=[r for r in live if bool(r.get(key))==flag and r.get('timestamp_ns')]
            for r in subset[::max(1,len(subset)//6)][:6]:sample_idx.add(int(np.argmin(abs(mapped-r['timestamp_ns']))))
    from .pilot_v3_faces import AuditFaceBackend
    backend=AuditFaceBackend();offline=[];images=[]
    try:
        with av.open(str(video)) as container:
            for index,frame in enumerate(container.decode(video=0)):
                if index not in sample_idx:continue
                image=frame.to_image();p=pts[index]
                try:f=backend.extract(image,p)
                except Exception as e:f={'face_present':False,'error':str(e)}
                row={**f,'frame_index':index,'pts_us':p,'estimated_elapsed_ns':int(mapped[index])};offline.append(row)
                if len(images)<24:
                    pic=image.copy();draw=ImageDraw.Draw(pic)
                    if f.get('face_box_normalized'):
                        box=f['face_box_normalized'];draw.rectangle([box[0]*pic.width,box[1]*pic.height,box[2]*pic.width,box[3]*pic.height],outline='red',width=3)
                        for x,y in f['eye_points_normalized']:draw.ellipse((x*pic.width-3,y*pic.height-3,x*pic.width+3,y*pic.height+3),fill='yellow')
                    pic.thumbnail((160,284));images.append((pic,f'frame {index} full={f.get("face_fully_in_frame_proxy")}'))
    finally:backend.close()
    write_jsonl(priv/'offline_face_observations.jsonl',offline)
    sheet=Image.new('RGB',(6*180,4*320),'white');draw=ImageDraw.Draw(sheet)
    for i,(im,text) in enumerate(images):sheet.paste(im,((i%6)*180,(i//6)*320));draw.text(((i%6)*180,(i//6)*320+286),text,fill='black')
    sheet.save(priv/'face_contact_sheet.jpg')
    offline_summary={'n':len(offline),'face_ratio':float(np.mean([r.get('face_present',False) for r in offline])),
        'strict_full_face_proxy_ratio':float(np.mean([r.get('face_fully_in_frame_proxy',False) for r in offline])),
        'edge_truncation_proxy_ratio':float(np.mean([r.get('edge_truncation_proxy',False) for r in offline])),
        'eyes_in_frame_proxy_ratio':float(np.mean([r.get('eye_in_frame_fraction_proxy')==1 for r in offline])),
        'bbox_area':describe([r.get('face_area_fraction') for r in offline]),'bbox_edge_margin':describe([r.get('edge_margin_normalized') for r in offline]),
        'missing_full_face_success_stratum':not any(r.get('face_fully_in_frame_proxy') for r in offline),'private_manual_review':str(priv/'face_contact_sheet.jpg')}
    write_json(out/'offline_face_summary.json',offline_summary)
    # Figures contain aggregate signals only; no face pixels in non-private output.
    fig,ax=plt.subplots(3,1,figsize=(12,8));t=(np.asarray(pts[:-1])-pts[0])/1e6
    ax[0].plot(t,1e6/np.diff(pts),linewidth=.5);ax[0].set_ylabel('Instant FPS')
    lt=[(r['timestamp_ns']-mapped[0])/1e9 for r in live if r.get('timestamp_ns')];lr=[r for r in live if r.get('timestamp_ns')]
    for key in ['yaw_proxy_deg','pitch_proxy_deg','roll_proxy_deg']:ax[1].plot(lt,[r.get(key,np.nan) for r in lr],label=key)
    ax[1].legend();ax[1].set_ylabel('Pose proxies (deg)');ax[2].plot(lt,[r.get('face_scale',np.nan) for r in lr]);ax[2].set_ylabel('Relative face scale');ax[2].set_xlabel('Estimated session video time (s)');fig.tight_layout();fig.savefig(priv/'face_and_recording_trajectories.png',dpi=130);plt.close(fig)
    plt.figure(figsize=(12,3));plt.plot(t,1e6/np.diff(pts),linewidth=.5);plt.ylabel('Instant encoded FPS');plt.xlabel('Video PTS time (s)');plt.tight_layout();plt.savefig(out/'figures/recording_fps.png',dpi=130);plt.close()
    btrials=[r for r in trials if r['task']=='visual_search'];plt.figure(figsize=(5,7));plt.scatter([r['target_x_norm'] for r in btrials],[r['target_y_norm'] for r in btrials],s=100,alpha=.3);plt.xlim(0,1);plt.ylim(1,0);plt.title('Recorded target positions; overlap indicates repetition');plt.xlabel('View normalized x');plt.ylabel('View normalized y');plt.tight_layout();plt.savefig(out/'figures/target_distribution.png',dpi=130);plt.close()
    from .pilot_v3_timeline import render_timeline
    render_timeline(trials,trial_data,mapped,assist,out/'timeline_visualization.html')
    breakdown=Counter()
    for p in root.rglob('*'):
        if p.is_file():breakdown['video' if p.suffix=='.mp4' else 'screenshots' if p.suffix=='.png' else 'json_metadata']+=p.stat().st_size
    write_json(out/'storage_breakdown.json',{'file_bytes':dict(breakdown),'phase_estimated_payload':phase_stats,'container_overhead_bytes':video.stat().st_size-int(packet_bytes.sum())})
    (out/'storage_breakdown.md').write_text('# Storage audit\n\n'+f'视频 {summary["video_MB"]:.2f} MB / {summary["video_MiB"]:.2f} MiB，{duration:.3f}s，实际码率 {summary["actual_bitrate_mbps"]:.2f} Mbps。\n\n'+''.join(f'- {k}: {v:,} bytes\n' for k,v in breakdown.items())+'\n阶段字节归因使用未验证的回调时间估计；不是精确物理对齐。\n\n'+''.join(f'- {k}: {v["estimated_duration_s"]:.2f}s, {v["encoded_payload_bytes"]/1e6:.2f} MB payload\n' for k,v in phase_stats.items())+'\nassistance_subset 与任务阶段重叠，不能相加。\n')
    (out/'timing_audit.md').write_text('# Timing audit\n\nMP4逐帧PTS与保存的encoded_frame一致。Recorder事件：'+str(Counter(r['type'] for r in summary['recorder_events']))+f'。Status callback-derived offset spread={summary["recorder_offset_spread_ms"]:.3f}ms，包含调度/编码延迟，不是同步误差。\n\n没有独立曝光/PTS锚点，全部14个trial不能进入“已验证对齐”的严格融合评估。Nearest frame residual仅为估计覆盖，物理uncertainty=null。\n\n可重复校准方案：将可见外部LED放在前摄画面角落，由微控制器输出伪随机光码并通过有线USB记录触发序列；Android用elapsedRealtime记录USB接收上下界，硬件独立记录发光触发。以MP4像素亮度检测每次LED跃迁，拟合PTS→elapsed的分段仿射映射；至少30个边沿、覆盖开始/结束及Pause/Resume，保留外部硬件延迟/USB调度区间、留出边沿误差和漂移。仅使用屏幕requestDraw或用户反应时都不是光子真值。若仅本机屏幕反射伪随机亮度，则只得到包含显示延迟的可重复估计，不能标validated。\n')
    repeated=Counter(r['target_text'] for r in btrials);missing=sum(not r['has_camera_features'] for r in trials)
    report=['# 2026-10-30 real Session audit','',f'Session `{session["session_id"]}`；manifest {len(declared)}文件hash通过、所有{len(pngs)}张PNG解码通过。原始文件只读。','',
        f'录像 {duration:.3f}s / {summary["video_MB"]:.2f}MB，{codec} {resolution}；整体 {summary["whole_session"]["effective_pts_fps"]:.2f}FPS；瞬时FPS {summary["whole_session"]["instant_fps"]}；>75ms缺口 {summary["whole_session"]["gaps_over_75ms"]}，重复PTS {summary["whole_session"]["duplicates"]}。阶段/逐trial见CSV与video_stats，不能用全程均值替代。','',
        f'ImageAnalysis {summary["analysis_fps"]:.2f}FPS；Live推理结果 {summary["inference_result_fps"]:.2f}FPS；成功face结果 {summary["successful_face_fps"]:.2f}FPS。Live face成功率 {summary["face_detection_success_ratio"]:.3%}；双眼in-frame代理 {summary["both_eyes_in_frame_proxy_ratio"]:.3%}；strict完整面部代理 {summary["strict_full_face_proxy_ratio"]:.3%}。','',
        f'离线{len(offline)}帧复核：{offline_summary}。人脸图与逐帧生物特征只保存private目录；公开报告不包含脸像。head pose/scale/blink均为模型代理，非gaze/距离/头姿真值。','',
        f'目标重复：{dict(repeated)}；无有效face特征trial {missing}/{len(trials)}；全部{len(trials)}个trial因缺独立时间锚点不用于严格验证的融合性能。','',
        f'Touch坐标/时钟一致性：{all(r["touch_coordinate_checks_ok"] for r in trials)}；帮助交付后对应UI均存在：{all(r["post_ui_observed"] and r["post_screenshot_exists"] for r in assistance)}。v2未显式记录assigned/requested的研究模式来源，按时间推断只能描述，不能当随机干预因果效果。','',
        '9个搜索trial均为同一目标“检查预约”；第一次求助后已暴露目标，后续速度存在记忆、位置、帮助、顺序和条件共同影响，不能把速度变化归因于字体/帮助单因素。font pair的元素变化字段见pair_audit。','',
        '自评均保留原始值；没有求助不代表没有困难。Helpfulness=0必须结合是否实际有帮助，不应当作零帮助收益。单人、重复目标、未验证同步：仅within-person feasibility，不能推断老年人总体或跨用户可靠性。','',
        '困难标签逐trial保存在trial_quality.csv，Fixation无自评分并且不是眼动真值；反馈是trial-level自报，不是逐帧困难起点。', '',
        '存储主要来自高码率全程录像；反馈/指导的估计时长和字节见storage_breakdown.md。应保留校准/交互段，长休息/反馈可选暂停，但必须显式记录视频缺口，不插值伪造观察。']
    (out/'session_audit.md').write_text('\n'.join(report)+'\n')
    after={p.relative_to(root).as_posix():sha256(p) for p in root.rglob('*') if p.is_file()}
    if original!=after:raise ValueError('Raw Session changed during audit')
    write_json(out/'preservation.json',{'raw_files':len(original),'raw_changed':False,'source_sha256':original})
    write_json(priv/'trial_inputs.json',trial_data);write_json(priv/'audit_index.json',{'mapped_elapsed_ns':mapped.tolist(),'pts_us':pts,'phase':phases})
    return {'audit':str(out/'session_audit.md'),'video_fps':summary['whole_session']['effective_pts_fps'],'live_fps':summary['inference_result_fps'],'raw_unchanged':True,'offline_faces':offline_summary}


if __name__=='__main__':print(json.dumps(audit_session(),ensure_ascii=False,indent=2))
