"""Private sampled clips and appearance/temporal caches, preserving exact selected PTS."""
from pathlib import Path
from fractions import Fraction
from collections import defaultdict
import json,time,av,numpy as np
from PIL import Image

def cache_training_inputs(private='reports/pilot_v3/private/temporal',video='data/derivatives/pilot_v3/test1030_20261030_144219/h264_720w_2mbps.mp4',output='data/derivatives/pilot_v3/test1030_20261030_144219/training_clips',report_output='reports/pilot_v3/temporal'):
    root=Path(private)
    if (root/'training_cache.npz').exists():raise ValueError('Training cache exists; choose a new private window directory')
    Path(report_output).mkdir(parents=True,exist_ok=True)
    windows=[json.loads(x) for x in (root/'windows.jsonl').read_text().splitlines()]
    output=Path(output);output.mkdir(exist_ok=False)
    writers=[];lookup=defaultdict(list);appearance=[]
    for k,row in enumerate(windows):
     path=output/f'window_{k:03d}.mp4';c=av.open(str(path),'w');s=c.add_stream('libx264',rate=4);s.width=480;s.height=854;s.pix_fmt='yuv420p';s.bit_rate=500000;s.codec_context.time_base=Fraction(1,1000000);s.codec_context.max_b_frames=0;s.codec_context.thread_count=1;s.options={'preset':'veryfast'}
     refs=row['short_video_clip'];first=refs['pts_us'][0] if refs['pts_us'] else 0
     writers.append((c,s,path,first))
     for i in refs['frame_indices']:lookup[i].append(k)
     crop=row['single_frame_face_crop']
     if crop and Path(crop).exists():
      with Image.open(crop) as im:appearance.append(np.asarray(im.convert('L').resize((16,16)),np.float32).reshape(-1)/255)
     else:appearance.append(np.full(256,np.nan,np.float32))
    start=time.perf_counter()
    with av.open(video) as container:
     for i,frame in enumerate(container.decode(video=0)):
      if i not in lookup:continue
      pts=int(frame.pts*frame.time_base*1000000)
      for k in lookup[i]:
       c,s,p,first=writers[k];f=frame.reformat(480,854,format='yuv420p');f.pts=pts-first;f.time_base=Fraction(1,1000000)
       for packet in s.encode(f):c.mux(packet)
    for c,s,p,first in writers:
     for packet in s.encode():c.mux(packet)
     c.close()
    manifest=[]
    for row,(_,_,path,first) in zip(windows,writers):
     with av.open(str(path)) as c:pts=[int(f.pts*f.time_base*1000000) for f in c.decode(video=0)]
     expected=[v-first for v in row['short_video_clip']['pts_us']];assert pts==expected
     manifest.append({'window_id':row['id'],'path':str(path),'source_pts_us':row['short_video_clip']['pts_us'],'clip_pts_us':pts,'source_cutoff_ns':row['cutoff_ns'],
      'physical_sync_status':'unverified','sampled_frames_only':True,'presentation_last_frame_hold_is_not_an_extra_observation':True})
    (root/'clip_manifest.json').write_text(json.dumps(manifest,indent=2))
    with np.load(root/'feature_cache.npz') as old:values={k:old[k] for k in old.files}
    values['single_frame_gray16x16']=np.array(appearance)
    values['single_frame_valid']=np.isfinite(values['single_frame_gray16x16']).all(axis=1)
    values['sequence_valid']=np.isfinite(values['sequence']);values['X_valid']=np.isfinite(values['X'])
    np.savez_compressed(root/'training_cache.npz',**values)
    report={'windows':len(windows),'actual_sampled_clips':len(manifest),'clip_bytes':sum(p.stat().st_size for _,_,p,_ in writers),'feature_cache_bytes':(root/'training_cache.npz').stat().st_size,
     'appearance_shape':list(values['single_frame_gray16x16'].shape),'extraction_seconds':time.perf_counter()-start,
     'all_clip_PTS_match_source_references':True,'video_encoder_trained':False,'physical_sync_status':'unverified','private_manifest':str(root/'clip_manifest.json')}
    (Path(report_output)/'cache_cost.json').write_text(json.dumps(report,indent=2));return report

if __name__=='__main__':print(cache_training_inputs())
