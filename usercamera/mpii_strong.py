"""Shared LOSO protocols for stronger probes; oracle conditions stay explicit."""
import json
import time
from pathlib import Path
import numpy as np
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from threadpoolctl import threadpool_limits

from .io import sha256,write_json,write_jsonl
from .geometry import angular_errors_deg
from .mpii_models import cnn_features,build_feature_sets,metadata_features
from .mpii_protocol import shared_splits,target_matrix,summarize_predictions,paired_subject_delta
from .mpii_finetune import fine_tune_loso,subset_training


@threadpool_limits.wrap(limits=1,user_api='blas')
def fit_ridge_probe(x,y,train,val,test,appearance_dims=0,alphas=(10,100,1000),validation_gaze=True):
    train=np.asarray(train,int);val=np.asarray(val,int);test=np.asarray(test,int)
    if set(train)&(set(val)|set(test)) or set(val)&set(test):raise ValueError('Overlapping partition IDs')
    scalers=[]
    if appearance_dims:
        scaler=StandardScaler().fit(x[train,:appearance_dims]);pca=PCA(n_components=min(32,len(train)-1,appearance_dims),svd_solver='randomized',random_state=42)
        pca.fit(scaler.transform(x[train,:appearance_dims]));scalers=[scaler,pca]
        def transform(indices):
            z=pca.transform(scaler.transform(x[indices,:appearance_dims]))
            return np.c_[z,extra.transform(x[indices,appearance_dims:])] if x.shape[1]>appearance_dims else z
        if x.shape[1]>appearance_dims:extra=StandardScaler().fit(x[train,appearance_dims:])
    else:
        scaler=StandardScaler().fit(x[train]);scalers=[scaler]
        def transform(indices):return scaler.transform(x[indices])
    a,b,c=transform(train),transform(val),transform(test);choices=[]
    for alpha in alphas:
        model=Ridge(alpha=alpha,solver='lsqr').fit(a,y[train]);pred=model.predict(b)
        score=float(angular_errors_deg(pred[:,:3],y[val,:3]).mean()) if validation_gaze else float(np.mean((pred-y[val])**2))
        choices.append((score,alpha,model))
    score,alpha,model=min(choices,key=lambda v:v[0])
    tick=time.perf_counter()
    for _ in range(20):model.predict(transform(test[:1]))
    ms=(time.perf_counter()-tick)*50
    return model.predict(c),{'alpha':alpha,'validation_score':score,'alphas':list(alphas),
                            'linear_parameters':int(model.coef_.size+model.intercept_.size),
                            'feature_to_prediction_batch1_ms':ms,'latency_excludes':'image decode, landmark detection and CNN encoder',
                            'pca_training_only':bool(appearance_dims)}


@threadpool_limits.wrap(limits=1,user_api='blas')
def crossfit_pose(appearance,rows,train,val,test):
    """Stacked pose features for TRAIN are participant-OOF, not in-sample fits."""
    y=np.asarray([metadata_features(r)['head_pose'] for r in rows])
    result=np.zeros_like(y);groups=np.array([r['subject_id'] for r in rows])
    def fit(a,b):
        scaler=StandardScaler().fit(appearance[a]);pca=PCA(n_components=min(32,len(a)-1),svd_solver='randomized',random_state=42)
        pca.fit(scaler.transform(appearance[a]));m=Ridge(alpha=100,solver='lsqr').fit(pca.transform(scaler.transform(appearance[a])),y[a])
        return m.predict(pca.transform(scaler.transform(appearance[b])))
    for a,b in GroupKFold(n_splits=3).split(train,groups=groups[train]):result[train[b]]=fit(train[a],train[b])
    result[np.r_[val,test]]=fit(train,np.r_[val,test])
    return result


def record_model(pred,rows):
    metrics,samples=summarize_predictions(pred,rows)
    per_subject={}
    for s in sorted({r['subject_id'] for r in rows}):
        idx=np.array([i for i,r in enumerate(rows) if r['subject_id']==s])
        per_subject[s]=summarize_predictions(pred[idx],[rows[i] for i in idx])[0]
    return {'metrics':metrics,'per_subject':per_subject},samples


def strong_baselines(root='data',output='reports/mpii_next/strong',splits_path='reports/mpii_next/splits.json',max_epochs=12,neural=True):
    root,output=Path(root),Path(output)
    rows,splits,manifest=shared_splits(root,splits_path);y=target_matrix(rows)
    appearance,source=cnn_features(rows,root);sets=build_feature_sets(rows,appearance)
    pose=np.array([metadata_features(r)['head_pose'] for r in rows]);cal=np.array([metadata_features(r)['calibration'] for r in rows])
    definitions={
        'original_pixels32x24_ridge':(*sets['pixels32x24_ridge'],(100,)),
        'landmark_oracle_head_pose_ridge':(*sets['landmarks_head_pose_ridge'],(10,100,1000)),
        'frozen_resnet18_224_face_eye_ridge':(appearance,1536,(10,100,1000)),
        'appearance_oracle_head_pose_ridge':(np.c_[appearance,pose],1536,(10,100,1000)),
        'appearance_known_hardware_calibration_ridge':(np.c_[appearance,cal],1536,(10,100,1000)),
        'frozen_resnet18_224_face_eye_ridge_n0.5':(appearance,1536,(10,100,1000))}
    predictions={};logs={};report={'split_sha256':sha256(splits_path),'protocol':manifest['protocol'],'n':len(rows),'models':{},
        'conditions':{'all_CNN_crops':'ground-truth supplied landmarks; no predicted-landmark detector',
                      'oracle_pose':'provided estimated 6-point head-model rotation+translation, not independent pose ground truth',
                      'predicted_pose':'experimental cross-participant stacked Ridge, assessed separately; not asserted reliable',
                      'calibration':'known hardware intrinsics/extrinsics, no user-specific gaze calibration',
                      'gaze_pretrained_weights':'none; only ImageNet initial weights',
                      'temporal_features':'not evaluated; no invented sequence ordering'},
        'not_completed':['predicted-landmark crop pipeline','external independently validated head-pose detector','gaze-specific architecture (optional)',
                         'geometry consistency LOSS ablation; only deterministic projection baseline evaluated'],
        'frozen_checkpoint_sha256':source['fingerprint']['weights_sha256']}
    prior=np.zeros_like(y);prior_logs=[]
    for fold,(train,val,test) in enumerate(splits):
        prior[test]=y[train].mean(0)
        prior_logs.append({'fold':fold,'train_n':len(train),'parameters':8,'inputs':'no image or test labels; outer training target means'})
    predictions['training_mean']=prior;logs['training_mean']=prior_logs
    report['models']['training_mean'],_=record_model(prior,rows)
    for name,(features,dims,alphas) in definitions.items():
        pred=np.zeros_like(y);history=[]
        for fold,(train,val,test) in enumerate(splits):
            if name.endswith('_n0.5'):train=subset_training(rows,train,.5)
            masked=y.copy();masked[test]=np.nan
            pred[test],log=fit_ridge_probe(features,masked,train,val,test,dims,alphas)
            history.append({'fold':fold,'train_n':len(train),**log})
        predictions[name]=pred;logs[name]=history
        report['models'][name],_=record_model(pred,rows)
        print('LOSO',name,round(report['models'][name]['metrics']['angular_error_deg']['mean'],3),flush=True)
    name='appearance_predicted_pose_crossfit_diagnostic';pred=np.zeros_like(y);pose_predictions=np.zeros_like(pose);history=[]
    for fold,(train,val,test) in enumerate(splits):
        p=crossfit_pose(appearance,rows,train,val,test);pose_predictions[test]=p[test]
        features=np.c_[appearance,p];masked=y.copy();masked[test]=np.nan
        pred[test],log=fit_ridge_probe(features,masked,train,val,test,1536)
        history.append({'fold':fold,**log})
    predictions[name]=pred;logs[name]=history;report['models'][name],_=record_model(pred,rows)
    write_jsonl(output/'predicted_pose.jsonl',[{'id':r['id'],'predicted_head_rvec':p[:3].tolist(),'predicted_head_translation_mm':(p[3:]*1000).tolist()} for r,p in zip(rows,pose_predictions)])
    if neural:
        p,history,architecture=fine_tune_loso(rows,splits,root,output,max_epochs=max_epochs)
        architecture['parameter_count_note']='full_backbone_parameters refers to original ImageNet classification model including unused fc1000; deployment encoder/cost counts exclude that fc'
        predictions.update(p);logs.update(history);report['neural_architecture']=architecture
        for name,pred in p.items():report['models'][name],_=record_model(pred,rows)
    else:report['not_completed'].append('fine-tuning and matched neural control (--no-neural)')
    report['training_logs']=logs
    from .mpii_benchmark import benchmark_encoder
    report['encoder_benchmark']=benchmark_encoder(root)
    for name,model in report['models'].items():
        neural_logs=logs[name]
        if name=='training_mean':
            model['cost']={'encoder_parameters':0,'linear_parameters_max_fold':8,'feature_to_prediction_median_ms':0.,'encoder_resolution':None,
                           'parameter_scope':'eight train-only mean constants; no encoder, zero timing is analytic (not measured)'}
        elif name.startswith(('finetuned_', 'matched_frozen_')):
            head=1536*128+128+128*8+8
            trainable=neural_logs[0]['selected']['trainable_parameters']
            times=[r['selected']['cached_tail_head_batch1_ms'] for r in neural_logs]
            model['cost']={'total_parameters':report['encoder_benchmark']['shared_encoder_parameters']+head,
                           'trainable_parameters':trainable,'cached_tail_or_head_median_ms':float(np.median(times)),
                           'encoder_resolution':64}
        else:
            use_encoder=name!='original_pixels32x24_ridge' and name!='landmark_oracle_head_pose_ridge'
            heads=max(r['linear_parameters'] for r in neural_logs)
            model['cost']={'encoder_parameters':report['encoder_benchmark']['shared_encoder_parameters'] if use_encoder else 0,
                           'linear_parameters_max_fold':heads,'feature_to_prediction_median_ms':float(np.median([r['feature_to_prediction_batch1_ms'] for r in neural_logs])),
                           'encoder_resolution':224 if use_encoder else None,
                           'parameter_scope':'encoder and Ridge coefficients; PCA/scaler arrays and pose stacking probe stored by implementation, not counted as neural weights'}
            if 'predicted_pose' in name:model['cost']['additional_pose_probe']='cross-fitted Ridge PCA32 -> 6 outputs (198 coefficients incl intercept), extra preprocessing; diagnostic only'
    comparisons={}
    for left,right in [('finetuned_layer4_n1','matched_frozen_head_n1'),('finetuned_layer4_n1','finetuned_layer4_n0.5'),
                       ('finetuned_layer4_n1','training_mean'),('frozen_resnet18_224_face_eye_ridge','training_mean'),
                       ('matched_frozen_head_n1','matched_frozen_head_n0.5'),
                       ('appearance_oracle_head_pose_ridge','appearance_predicted_pose_crossfit_diagnostic'),
                       ('appearance_oracle_head_pose_ridge','frozen_resnet18_224_face_eye_ridge'),
                       ('appearance_predicted_pose_crossfit_diagnostic','frozen_resnet18_224_face_eye_ridge'),
                       ('appearance_known_hardware_calibration_ridge','frozen_resnet18_224_face_eye_ridge'),
                       ('frozen_resnet18_224_face_eye_ridge','frozen_resnet18_224_face_eye_ridge_n0.5')]:
        if left in report['models'] and right in report['models']:
            subjects=list(report['models'][left]['per_subject'])
            comparisons[left+' minus '+right]=paired_subject_delta(
                [report['models'][left]['per_subject'][s]['angular_error_deg']['mean'] for s in subjects],
                [report['models'][right]['per_subject'][s]['angular_error_deg']['mean'] for s in subjects])
    report['paired_comparisons']=comparisons
    write_json(output/'strong_results.json',report)
    sample_errors=[]
    for name,pred in predictions.items():
        _,errors=summarize_predictions(pred,rows)
        for row,error in zip(rows,errors):sample_errors.append({'id':row['id'],'subject_id':row['subject_id'],'model':name,**error})
    write_jsonl(output/'prediction_errors.jsonl',sample_errors)
    write_jsonl(output/'invalid_rays.jsonl',[e for e in sample_errors if not e['predicted_origin_ray']['valid']])
    main='finetuned_layer4_n1' if 'finetuned_layer4_n1' in predictions else 'frozen_resnet18_224_face_eye_ridge'
    write_jsonl(output/'worst20.jsonl',sorted([e for e in sample_errors if e['model']==main],key=lambda e:e['angular_error_deg'],reverse=True)[:20])
    write_jsonl(output/'predictions.jsonl',[{'id':r['id'],'subject_id':r['subject_id'],
                     'fold':next(k for k,(_,_,t) in enumerate(splits) if i in t),
                     'models':{name:p[i].tolist() for name,p in predictions.items()}} for i,r in enumerate(rows)])
    return {'report':str(output/'strong_results.json'),'models':list(report['models']),'n':len(rows)}
