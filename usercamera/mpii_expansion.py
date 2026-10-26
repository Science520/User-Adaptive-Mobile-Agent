"""Integrate already-downloaded images without touching v1 data/results."""
import json
import time
from collections import Counter
from pathlib import Path
import numpy as np
from PIL import Image
from threadpoolctl import threadpool_limits

from .io import read_jsonl, write_json, write_jsonl, sha256
from .geometry import gaze_vector
from .mpii_outlier_audit import raw_annotations, view_ids
from .mpii_protocol import make_splits, target_matrix, summarize_predictions, paired_subject_delta
from .mpii_strong import fit_ridge_probe, record_model


def verified_files(base, records):
    base=Path(base).resolve(); ids=set()
    for r in records:
        member=r['member'];p=(base/member).resolve()
        if not p.is_relative_to(base) or member in ids:raise ValueError('Escaping/duplicate manifest member')
        ids.add(member)
        if not p.is_file() or sha256(p)!=r['sha256'] or p.stat().st_size!=r['bytes']:
            raise ValueError('Manifest hash/size mismatch: '+member)
        if p.suffix.lower() in ('.jpg','.jpeg','.png'):
            with Image.open(p) as im:im.verify()
    return ids


def immutable_json(path,obj):
    path=Path(path)
    if path.exists() and json.loads(path.read_text())!=obj:raise ValueError('Immutable view differs; choose a new version: '+str(path))
    if not path.exists():write_json(path,obj)


def integrate_expansion(root='data',expansion='data/expansions/mpii_v1',output='reports/mpii_expansion'):
    root,expansion,output=Path(root),Path(expansion),Path(output)
    mpath=expansion/'manifest.json';m=json.loads(mpath.read_text())
    original_manifest=root/'raw/mpiifacegaze/manifest.json';om=json.loads(original_manifest.read_text())
    verified_files(original_manifest.parent,om['files']);new_ids=verified_files(expansion,m['new_files'])
    actual={str(p.relative_to(expansion)) for p in expansion.rglob('*.jpg')}
    if actual!=new_ids:raise ValueError('Actual expansion JPEG set differs from manifest')
    if new_ids!=set(m['plan']['extra_image_ids']):raise ValueError('Expansion plan/sample IDs mismatch')
    if m['plan']['original_manifest_sha256']!=sha256(original_manifest):raise ValueError('Original manifest changed')
    old=read_jsonl(root/'processed/mpii.jsonl');old_ids={r['id'] for r in old}
    if len(old_ids)!=len(old) or old_ids!=set(om['selected_images']):raise ValueError('Original processed/sample manifest mismatch')
    if old_ids&new_ids:raise ValueError('Expansion overlaps original image IDs')
    all_rows,invalid=raw_annotations(root);lookup={r['id']:r for r in all_rows}
    if invalid or not new_ids<=set(lookup):raise ValueError('Invalid or missing official annotations')
    extra=[]
    for key in sorted(new_ids):
        raw=lookup[key];r={k:raw[k] for k in ['id','subject_id','gaze_screen_px','screen_size_px','landmarks_2d','head_rvec',
            'head_translation_mm','face_center_mm','gaze_target_mm','eye_subset','calibration']}
        p=(expansion/key).resolve()
        with Image.open(p) as im:width,height=im.size
        r.update(source='MPIIFaceGaze',image_path=str(p),image_width=width,image_height=height,
            gaze_direction=gaze_vector(r['face_center_mm'],r['gaze_target_mm']).tolist(),
            face_camera_distance_proxy_mm=float(np.linalg.norm(r['face_center_mm'])),camera_matrix=r['calibration']['camera']['K'],
            schema_version='mpii-sample-v2',temporal=False,label_provenance='official gaze target; estimated head pose/face center',
            head_pose_convention=old[0]['head_pose_convention'])
        extra.append(r)
    combined=sorted(old+extra,key=lambda r:r['id']);view=root/'views/mpii_v2_720'
    manifest={'schema':'mpii-expanded-view-v1','original_ids':sorted(old_ids),'expansion_ids':sorted(new_ids),
        'original_processed_sha256':sha256(root/'processed/mpii.jsonl'),'original_manifest_sha256':sha256(original_manifest),
        'expansion_manifest_sha256':sha256(mpath),'n':len(combined),'subjects':dict(Counter(r['subject_id'] for r in combined)),
        'image_hashes':{r['id']:sha256(r['image_path']) for r in combined}}
    immutable_json(view/'manifest.json',manifest)
    samples=view/'processed/mpii.jsonl'
    if samples.exists() and read_jsonl(samples)!=combined:raise ValueError('Immutable processed v2 view differs')
    if not samples.exists():write_jsonl(samples,combined)
    split={'schema':'loso-inner-participant-v1','source_sha256':sha256(samples),'splits':make_splits(combined),
           'protocol':'720 diagnostic tests; primary training-size comparison holds original360 test and validation IDs fixed'}
    immutable_json(view/'splits.json',split)
    views=view_ids(all_rows)
    report={'view':str(view),'n_original':len(old),'n_expansion':len(extra),'n_total':len(combined),
        'original_file_hashes_verified':len(om['files']),'new_file_hashes_and_decode_verified':len(extra),
        'expansion_membership':{k:len(new_ids&set(ids)) for k,ids in views.items()},
        'combined_membership':{k:len((old_ids|new_ids)&set(ids)) for k,ids in views.items()},
        'outside_expansion_ids':sorted(new_ids-set(views['On-screen'])),
        'bad_day_expansion_ids':sorted(new_ids-set(views['Day-filtered'])),
        'view_manifest_sha256':sha256(view/'manifest.json'),'dataset_downloads':0,'temporal':False}
    write_json(output/'integration.json',report)
    return report


def expanded_features(root,view,rows):
    """Reuse old embeddings; encode only new images in independent cache tree."""
    from .mpii_models import cnn_features,WEIGHTS_NAME
    old=read_jsonl(root/'processed/mpii.jsonl');ids={r['id'] for r in old}
    previous,_=cnn_features(old,root)
    extra=[r for r in rows if r['id'] not in ids];work=view/'extra_features'
    weights=work/'cache/torch/hub/checkpoints'/WEIGHTS_NAME
    weights.parent.mkdir(parents=True,exist_ok=True)
    if not weights.exists():weights.symlink_to((root/'cache/torch/hub/checkpoints'/WEIGHTS_NAME).resolve())
    new,source=cnn_features(extra,work)
    lookup={r['id']:v for r,v in zip(old,previous)};lookup.update({r['id']:v for r,v in zip(extra,new)})
    return np.stack([lookup[r['id']] for r in rows]),source


def expanded_protocol(root,view,rows):
    old=json.loads(Path('reports/mpii_next/splits.json').read_text())
    if old['source_sha256']!=sha256(root/'processed/mpii.jsonl'):raise ValueError('v1 split source mismatch')
    index={r['id']:i for i,r in enumerate(rows)};folds=[];records=[]
    for f in old['splits']:
        train=np.array([index[k] for k in f['train_ids']]);val=np.array([index[k] for k in f['validation_ids']]);test=np.array([index[k] for k in f['test_ids']])
        expanded=np.array([i for i,r in enumerate(rows) if r['subject_id'] not in [f['test_subject'],f['validation_subject']]])
        new_test=np.array([i for i,r in enumerate(rows) if r['subject_id']==f['test_subject'] and r['id'] not in f['test_ids']])
        groups=[{rows[i]['subject_id'] for i in ix} for ix in [expanded,val,np.r_[test,new_test]]]
        if groups[0]&groups[1] or groups[0]&groups[2] or groups[1]&groups[2]:raise ValueError('Participant leakage')
        folds.append((train,expanded,val,test,new_test))
        records.append({**f,'expanded_train_ids':[rows[i]['id'] for i in expanded],'new_test_ids':[rows[i]['id'] for i in new_test]})
    obj={'v1_split_sha256':sha256('reports/mpii_next/splits.json'),'v2_view_sha256':sha256(view/'manifest.json'),
         'primary':'same original360 test IDs and original24 validation IDs per fold; only training changes 312->624',
         'secondary':'new360 heldout-subject test images reported separately; not an improvement comparison','folds':records}
    immutable_json(view/'comparison_splits.json',obj)
    return folds,obj


@threadpool_limits.wrap(limits=1,user_api='blas')
def evaluate_expanded(root='data',output='reports/mpii_expansion',run_neural=False,max_epochs=12):
    root,output=Path(root),Path(output);view=root/'views/mpii_v2_720'
    rows=read_jsonl(view/'processed/mpii.jsonl');folds,protocol=expanded_protocol(root,view,rows)
    x,_=expanded_features(root,view,rows);y=target_matrix(rows)
    predictions={};logs={};old_indices=np.concatenate([f[3] for f in folds]);new_indices=np.concatenate([f[4] for f in folds])
    for condition,training_index in [('original360',0),('expanded720',1)]:
        p=np.zeros_like(y);history=[]
        for train_old,train_new,val,test,extra in folds:
            train=[train_old,train_new][training_index];masked=y.copy();masked[np.r_[test,extra]]=np.nan
            p[np.r_[test,extra]],log=fit_ridge_probe(x,masked,train,val,np.r_[test,extra],1536)
            history.append({'train_n':len(train),'validation_n':len(val),'original_test_n':len(test),'new_test_n':len(extra),**log})
        name='frozen_224_ridge_'+condition;predictions[name]=p;logs[name]=history
    old_logs=json.loads(Path('reports/mpii_next/strong/strong_results.json').read_text())['training_logs']['finetuned_layer4_n1']
    previous_seconds=sum(c['training_seconds'] for fold in old_logs for c in fold['candidates'])
    estimate={'previous_312_train_cpu_seconds':previous_seconds,'expanded_624_train_cpu_seconds_estimate':previous_seconds*2,
        'estimate_scope':'15 folds, same two lr/wd candidates, up to12 epochs; scale linearly by training size; early stopping/host load vary',
        'cached_720_stem_float32_mib':720*3*256*4*4*4/1024**2,'rough_process_ram_mib':600,
        'training_enabled':run_neural,'max_epochs':max_epochs}
    write_json(output/'neural_resource_estimate.json',estimate)
    print('Neural resource estimate:',json.dumps(estimate),flush=True)
    if run_neural:
        import torch
        from .mpii_finetune import prepare_stem,train_one
        # Isolated cache; checkpoint symlink is the same existing ImageNet checkpoint.
        from .mpii_models import WEIGHTS_NAME
        weights=view/'cache/torch/hub/checkpoints'/WEIGHTS_NAME;weights.parent.mkdir(parents=True,exist_ok=True)
        if not weights.exists():weights.symlink_to((root/'cache/torch/hub/checkpoints'/WEIGHTS_NAME).resolve())
        maps,embedding,base,stem=prepare_stem(rows,view)
        for condition,index in [('original360',0),('expanded720',1)]:
            if condition=='original360' and max_epochs==12:
                # Exact previously executed control: same IDs/ordering, trainer, seed, candidates and 12-epoch cap.
                trainer_hash=sha256(Path(__file__).with_name('mpii_finetune.py'))
                for f,old_log in zip(folds,old_logs):
                    sig=old_log['signature']
                    if sig['code_sha256']!=trainer_hash or sig['max_epochs']!=12 or sig['train_ids']!=[rows[i]['id'] for i in f[0]] or sig['val_ids']!=[rows[i]['id'] for i in f[2]] or sig['test_ids']!=[rows[i]['id'] for i in f[3]]:
                        raise ValueError('Cannot reuse old fine-tuning control: protocol differs')
                saved={r['id']:r['models']['finetuned_layer4_n1'] for r in read_jsonl('reports/mpii_next/strong/predictions.jsonl')}
                p=np.full_like(y,np.nan)
                for i in old_indices:p[i]=saved[rows[i]['id']]
                predictions['finetuned_64_original360']=p;logs['finetuned_64_original360']={'reused_exact_v1_control':True,'new_test_predictions_available':False}
                continue
            p=np.zeros_like(y);history=[]
            for k,f in enumerate(folds):
                train=f[index];val,test,extra=f[2:];evaluated=np.r_[test,extra]
                sig={'code':sha256(__file__),'trainer':sha256(Path(__file__).with_name('mpii_finetune.py')),
                     'view':sha256(view/'manifest.json'),'fold':k,'condition':condition,'max_epochs':max_epochs,'split':sha256(view/'comparison_splits.json')}
                cache=output/'neural_folds'/condition/f'fold_{k:02d}.json'
                if cache.exists() and json.loads(cache.read_text()).get('signature')==sig:
                    saved=json.loads(cache.read_text())
                else:
                    target=torch.tensor(y,dtype=torch.float32);target[evaluated]=float('nan')
                    choices=[]
                    for config in [{'lr':1e-4,'weight_decay':1e-4},{'lr':3e-4,'weight_decay':1e-3}]:
                        pp,log=train_one(maps,embedding,base,target,train,val,evaluated,config,True,max_epochs)
                        choices.append((pp,log))
                    selected=min(range(2),key=lambda i:choices[i][1]['validation_angular_deg'])
                    saved={'signature':sig,'predictions':choices[selected][0].tolist(),'selected':selected,'candidates':[c[1] for c in choices]}
                    write_json(cache,saved)
                p[evaluated]=saved['predictions'];history.append(saved)
                print('expanded partial fine-tuning',condition,k+1,'/15',flush=True)
            predictions['finetuned_64_'+condition]=p;logs['finetuned_64_'+condition]=history
    report={'protocol':protocol,'primary_original360':{},'secondary_new360':{},'paired_comparisons':{},'training_logs':logs,
        'neural_resource_estimate':estimate,'dataset_downloads':0,'conditions':'supplied landmark crops, ImageNet initial weights, known hardware for ray projection; no test gaze as input',
        'neural_completed':run_neural,'evidence_tier':'static_public_images_not_mobile_temporal'}
    for name,p in predictions.items():
        report['primary_original360'][name]=record_model(p[old_indices],[rows[i] for i in old_indices])[0]
        report['secondary_new360'][name]=record_model(p[new_indices],[rows[i] for i in new_indices])[0] if np.isfinite(p[new_indices]).all() else None
    for family in ['frozen_224_ridge','finetuned_64']:
        a,b=family+'_expanded720',family+'_original360'
        if a in predictions:
            sa,sb=report['primary_original360'][a]['per_subject'],report['primary_original360'][b]['per_subject']
            report['paired_comparisons'][family]=paired_subject_delta([sa[k]['angular_error_deg']['mean'] for k in sorted(sa)],
                                                                        [sb[k]['angular_error_deg']['mean'] for k in sorted(sb)])
    write_json(output/'expanded_results.json',report)
    write_jsonl(output/'predictions.jsonl',[{'id':r['id'],'subject_id':r['subject_id'],'test_cohort':'original360' if i in set(old_indices) else 'new360',
             'models':{name:p[i].tolist() for name,p in predictions.items()}} for i,r in enumerate(rows)])
    lines=['# MPII expansion: fixed-test sample-size comparison','',protocol['primary'],
           '', '| Model | Original test360 angular mean° | Screen mean mm | New test360 angular mean° (separate cohort) |','|---|---:|---:|---:|']
    for name,v in report['primary_original360'].items():
        m=v['metrics'];other=report['secondary_new360'][name];new_score=f"{other['metrics']['angular_error_deg']['mean']:.3f}" if other else 'not computed (exact old control has no saved checkpoint)'
        lines.append(f"| {name} | {m['angular_error_deg']['mean']:.3f} | {m['screen_direct_error_mm']['mean']:.2f} | {new_score} |")
    lines+=['',json.dumps(report['paired_comparisons'],ensure_ascii=False,indent=2),'',
        'Negative paired delta means expanded training lowers error on the SAME original360 test IDs. Bootstrap is descriptive, no repeated training.',
        'New test360 results measure changed test composition, not model improvement. No gaze-specific pretrained weights. No synchronized mobile/difficulty evidence.',
        'Neural executed: '+str(run_neural)+'. Resource estimate is in neural_resource_estimate.json. Original v1 manifests, processed files, caches and reports preserved.']
    (output/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    return {'report':str(output/'RESULTS.md'),'models':list(predictions),'neural_completed':run_neural}
