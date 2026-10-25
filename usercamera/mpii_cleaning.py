"""Immutable cleaning views and paired training-set sensitivity on fixed tests."""
import json
import csv
from pathlib import Path
import numpy as np
from threadpoolctl import threadpool_limits

from .io import read_jsonl,sha256,write_json,write_jsonl
from .mpii_outlier_audit import raw_annotations,view_ids
from .mpii_protocol import shared_splits,target_matrix,summarize_predictions,paired_subject_delta
from .mpii_models import build_feature_sets,cnn_features,fit_predict_fold


def expansion_plan(root='data',extra_per_subject=24):
    if extra_per_subject < 0:raise ValueError('Additional sample count must be nonnegative')
    root=Path(root);all_rows,_=raw_annotations(root)
    current={r['id'] for r in read_jsonl(root/'processed/mpii.jsonl')}
    rng=np.random.default_rng(42);selected=[]
    for s in sorted({r['subject_id'] for r in all_rows}):
        candidates=[r['id'] for r in all_rows if r['subject_id']==s and r['id'] not in current]
        selected.extend(rng.choice(candidates,min(extra_per_subject,len(candidates)),replace=False).tolist())
    sizes=[Path(r['image_path']).stat().st_size for r in read_jsonl(root/'processed/mpii.jsonl')]
    # Existing sampler reads up to 64KiB extra per member, plus the ~8MiB ZIP directory.
    typical=(8*1024**2+len(selected)*(np.mean(sizes)+65535))/1024**2
    conservative=(12*1024**2+len(selected)*(max(sizes)+65535))/1024**2
    return {'schema':'planned-expansion-v1','extra_image_ids':selected,'new_images':len(selected),
            'sampling':'seed42 random within each participant, excludes original360',
            'planned_view_counts':{k:len(set(selected)&set(ids)) for k,ids in view_ids(all_rows).items()},
            'estimated_transfer_mib':float(typical),'conservative_observed_size_estimate_mib':float(conservative),
            'estimate_note':'based on observed local JPEG sizes; not a guaranteed bound. Actual byte-budget enforced by Range reader.',
            'original_manifest_sha256':sha256(root/'raw/mpiifacegaze/manifest.json'),'allow_download_required':True}


def download_expansion(root,plan,destination,budget_mib=64,allow_download=False):
    if not allow_download:raise ValueError('Explicit --allow-download required; no dataset request issued')
    if budget_mib<=0 or budget_mib>192:raise ValueError('Budget must be 0..192 MiB (existing per-ZIP maximum)')
    destination=Path(destination)
    if destination.exists():raise ValueError('Use a new expansion directory/version; never overwrite a manifest')
    from .download import RemoteZipFile,extract_remote_selected
    import zipfile
    # Stable public file ID and byte size already present in local metadata; no full-file download.
    remote=RemoteZipFile('https://darus.uni-stuttgart.de/api/access/datafile/198951',957192215,
                         max_bytes=int(budget_mib*1024**2),block_size=4*1024**2)
    try:
        with zipfile.ZipFile(remote) as archive:
            names=plan['extra_image_ids']
            infos=[archive.getinfo(n) for n in names]
            projected=remote.transferred+sum(30+len(i.filename.encode())+65535+i.compress_size for i in infos)
            if projected>remote.limit:raise ValueError(f'Planned transfer {projected/1024**2:.1f} MiB exceeds budget; reduce sample count')
            files=extract_remote_selected(remote,archive,names,destination)
        write_json(destination/'manifest.json',{'plan':plan,'new_files':files,'range_bytes':remote.transferred,
                    'original_manifest_unchanged':True,'scope':'new images only; not the official dataset and not the original 360 manifest'})
        return {'manifest':str(destination/'manifest.json'),'new_images':len(files),'range_bytes':remote.transferred}
    except Exception:
        if destination.exists():write_json(destination/'incomplete.json',{'range_bytes':remote.transferred,'complete':False})
        raise


@threadpool_limits.wrap(limits=1,user_api='blas')
def compare_cleaning(root='data',output='reports/mpii_next/cleaning',splits_path='reports/mpii_next/splits.json',
                     extra_per_subject=24,allow_download=False,download_budget_mib=64,expansion_dir='data/expansions/mpii_v1'):
    root,output=Path(root),Path(output)
    full,_=raw_annotations(root);views=view_ids(full)
    rows,splits,split_manifest=shared_splits(root,splits_path)
    y=target_matrix(rows);index={r['id']:i for i,r in enumerate(rows)}
    # Avoid repeatedly constructing ID sets for each row on full datasets.
    memberships={name:np.array([r['id'] in lookup for r in rows]) for name,lookup in [(k,set(v)) for k,v in views.items()]}
    write_json(output/'views_manifest.json',{'source_split_sha256':sha256(splits_path),'full_annotation_views':views,
                'current_image_ids':{k:[r['id'] for r,keep in zip(rows,m) if keep] for k,m in memberships.items()},
                'labels_modified':False,'continuous_boundary':'[0,W] x [0,H]'})
    distribution=[]
    for scope,pool in [('all_annotations',full),('local_images',rows)]:
        for view,ids in views.items():
            lookup=set(ids)
            for subject in sorted({r['subject_id'] for r in pool}):
                group=[r for r in pool if r['id'] in lookup and r['subject_id']==subject]
                uv=np.array([np.asarray(r['gaze_screen_px'])/r['screen_size_px'] for r in group])
                distribution.append({'scope':scope,'view':view,'subject_id':subject,'n':len(group),
                    'days':len({r.get('day',Path(r['id']).parent.name) for r in group}),
                    'mean_x_over_W':float(uv[:,0].mean()) if len(group) else None,
                    'mean_y_over_H':float(uv[:,1].mean()) if len(group) else None,
                    'std_x_over_W':float(uv[:,0].std()) if len(group) else None,
                    'std_y_over_H':float(uv[:,1].std()) if len(group) else None})
    with (output/'view_distributions.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(distribution[0]));writer.writeheader();writer.writerows(distribution)
    appearance,_=cnn_features(rows,root);features=build_feature_sets(rows,appearance)
    wanted=['pixels32x24_ridge','landmarks_head_pose_ridge','face_eye_cnn_ridge'];results={};predictions={}
    for model in wanted:
        results[model]={};predictions[model]={}
        for view,mask in memberships.items():
            pred=np.zeros_like(y);counts=[]
            x,appearance_dims=features[model]
            for train,val,test in splits:
                retained=train[mask[train]]
                if len(retained)<3:raise ValueError('Insufficient cleaned training samples')
                pred[test]=fit_predict_fold(x,y,retained,test,appearance_dims)
                counts.append({'train_n':len(retained),'train_ids':[rows[i]['id'] for i in retained],
                               'validation_ids':[rows[i]['id'] for i in val],'fixed_test_ids':[rows[i]['id'] for i in test]})
            metrics,samples=summarize_predictions(pred,rows)
            # Same fitted model, then restrict its test set: explicitly a difficulty/composition change, NOT train-cleaning benefit.
            test_subsets={}
            for test_view,test_mask in memberships.items():
                ids=np.flatnonzero(test_mask)
                test_subsets[test_view]=summarize_predictions(pred[ids],[rows[i] for i in ids])[0]
            per_subject={s:summarize_predictions(pred[[i for i,r in enumerate(rows) if r['subject_id']==s]],
                                               [r for r in rows if r['subject_id']==s])[0]
                         for s in sorted({r['subject_id'] for r in rows})}
            results[model][view]={'fixed_original_test_metrics':metrics,'folds':counts,'per_subject':per_subject,
                                  'test_restriction_sensitivity_same_fitted_model':test_subsets}
            predictions[model][view]=pred
            print('cleaning',model,view,round(metrics['angular_error_deg']['mean'],3),flush=True)
    comparisons={}
    for model in wanted:
        subjects=list(results[model]['Original']['per_subject'])
        for view in ['On-screen','Day-filtered']:
            left=[results[model][view]['per_subject'][s]['angular_error_deg']['mean'] for s in subjects]
            right=[results[model]['Original']['per_subject'][s]['angular_error_deg']['mean'] for s in subjects]
            comparisons[model+': '+view+' train minus Original train']=paired_subject_delta(left,right)
    plan=expansion_plan(root,extra_per_subject)
    write_json(output/'expansion_plan.json',plan)
    report={'n_images':len(rows),'split_sha256':sha256(splits_path),'protocol':split_manifest['protocol'],
            'view_image_counts':{k:int(v.sum()) for k,v in memberships.items()},
            'all_three_image_views_identical':all(np.array_equal(memberships['Original'],v) for v in memberships.values()),
            'original_and_on_screen_identical':np.array_equal(memberships['Original'],memberships['On-screen']),
            'train_cleaning_fixed_test':results,'paired_comparisons':comparisons,'expansion_plan':plan,
            'note':'No current image has an outside label; direct removal of the 243 outside images cannot be tested without new photos. Day-filtered removes valid-label photos collected on affected days.',
            'dataset_downloads':0}
    if allow_download:
        print(json.dumps({'download_plan_before_request':plan},ensure_ascii=False),flush=True)
        report['expansion_download']=download_expansion(root,plan,expansion_dir,download_budget_mib,True)
        report['dataset_downloads']=plan['new_images']
    write_json(output/'cleaning_results.json',report)
    write_jsonl(output/'predictions.jsonl',[{'id':r['id'],'subject_id':r['subject_id'],
                   'predictions':{m:{v:p[i].tolist() for v,p in vv.items()} for m,vv in predictions.items()}}
                 for i,r in enumerate(rows)])
    return {'report':str(output/'cleaning_results.json'),'view_counts':report['view_image_counts'],
            'estimated_additional_download_mib':plan['estimated_transfer_mib'],'dataset_downloads':report['dataset_downloads']}
