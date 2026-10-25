"""Snapshot localization/pose/proxy tasks; NOT human difficulty or temporal cues."""
from pathlib import Path
import json
import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score,confusion_matrix
from threadpoolctl import threadpool_limits

from .io import read_jsonl,sha256,write_json,write_jsonl
from .mpii_models import cnn_features,crop_boxes
from .mpii_protocol import shared_splits,paired_subject_delta
from .mpii_strong import fit_ridge_probe
from .camera_screen_geometry import intersect_gaze


def zone_labels(uv,grid):
    if not isinstance(grid,int) or grid<1:raise ValueError('Grid must be a positive integer')
    uv=np.asarray(uv,float)
    if uv.ndim!=2 or uv.shape[1]!=2:raise ValueError('Expected Nx2 normalized coordinates')
    valid=np.isfinite(uv).all(1)&(uv>=0).all(1)&(uv<=1).all(1)
    result=np.full(len(uv),-1,int)
    xy=np.minimum(np.floor(uv[valid]*grid).astype(int),grid-1)
    result[valid]=xy[:,1]*grid+xy[:,0]
    return result


def region_labels(uv):
    uv=np.asarray(uv,float);valid=np.isfinite(uv).all(1)&(uv>=0).all(1)&(uv<=1).all(1)
    labels=np.full(len(uv),-1,int);labels[valid]=np.minimum((uv[valid,0]*3).astype(int),2)
    return labels


def classification_scores(y,pred,k):
    y,pred=np.asarray(y),np.asarray(pred);valid=y>=0
    yy,pp=y[valid],pred[valid]
    if not len(yy):return {'n':0,'macro_f1':None,'balanced_accuracy':None,'accuracy':None}
    recall=[float(np.mean(pp[yy==c]==c)) for c in range(k) if (yy==c).any()]
    # -1 predictions are explicit failure/abstention: counted wrong, never removed.
    matrix=np.zeros((k,k+1),int)
    for a,b in zip(yy,pp):matrix[a,b if 0<=b<k else k]+=1
    return {'n':len(yy),'excluded_outside_true_target':int((~valid).sum()),
            'macro_f1':float(f1_score(yy,pp,labels=list(range(k)),average='macro',zero_division=0)),
            'balanced_accuracy':float(np.mean(recall)),'accuracy':float(np.mean(yy==pp)),
            'invalid_predictions_counted_wrong':int(((pp<0)|(pp>=k)).sum()),
            'labels':list(range(k)),'confusion_matrix_last_column_invalid':matrix.tolist(),
            'macro_f1_label_universe':'all grid classes even if absent in one participant',
            'balanced_accuracy_label_universe':'classes with actual support in this scoring set'}


def camera_status(row):
    path=Path(row['image_path'])
    if not path.exists():return 'missing_image'
    try:
        with Image.open(path) as image:
            a=np.asarray(image.convert('L'))
            if a.max()==a.min():return 'constant_frame'
        crop_boxes(row)
    except (ValueError,OSError):return 'decode_or_landmark_failure'
    return 'passed_structural_checks'


@threadpool_limits.wrap(limits=1,user_api='blas')
def coarse_eval(root='data',output='reports/mpii_next/coarse',strong_output='reports/mpii_next/strong',splits_path='reports/mpii_next/splits.json'):
    root,output,strong_output=Path(root),Path(output),Path(strong_output)
    rows,splits,manifest=shared_splits(root,splits_path)
    source=json.loads((strong_output/'strong_results.json').read_text())
    if source['split_sha256']!=sha256(splits_path):raise ValueError('Strong/coarse split mismatch')
    records=read_jsonl(strong_output/'predictions.jsonl');by_id={r['id']:r for r in records}
    if len(records)!=len(by_id) or set(by_id)!={r['id'] for r in rows}:raise ValueError('Prediction/sample ID mismatch or duplicates')
    for fold,(_,_,test) in enumerate(splits):
        for i in test:
            saved=by_id[rows[i]['id']]
            if saved['fold']!=fold or saved['subject_id']!=rows[i]['subject_id']:raise ValueError('Prediction fold/participant provenance mismatch')
    appearance,_=cnn_features(rows,root)
    uv=np.array([np.array(r['gaze_screen_px'])/r['screen_size_px'] for r in rows])
    specs={f'{k}x{k}':(k*k,zone_labels(uv,k),lambda p,k=k:zone_labels(p,k)) for k in [2,3,4]}
    specs['left_center_right']=(3,region_labels(uv),region_labels)
    result={'split_sha256':sha256(splits_path),'n':len(rows),'tasks':{},'not_difficulty_labels':True,
            'temporal_claims':False,'conditions':'all learned appearance inputs use supplied landmark crops; static image evaluation only'}
    subjects=np.array([r['subject_id'] for r in rows]);raw_pred={}
    for task,(k,truth,labeler) in specs.items():
        models={};chosen_class=np.full(len(rows),-1,int);prior=np.full(len(rows),-1,int);selection=[]
        for fold,(train,val,test) in enumerate(splits):
            train=train[truth[train]>=0];val=val[truth[val]>=0]
            scaler=StandardScaler().fit(appearance[train]);pca=PCA(n_components=min(32,len(train)-1),svd_solver='randomized',random_state=42,whiten=True)
            a=pca.fit_transform(scaler.transform(appearance[train]));b=pca.transform(scaler.transform(appearance[val]));c=pca.transform(scaler.transform(appearance[test]))
            candidates=[]
            for strength in [.1,1,10]:
                classifier=LogisticRegression(C=strength,max_iter=5000,random_state=42).fit(a,truth[train])
                score=classification_scores(truth[val],classifier.predict(b),k)['macro_f1'];candidates.append((score,strength,classifier))
            score,strength,classifier=max(candidates,key=lambda x:x[0]);chosen_class[test]=classifier.predict(c)
            prior[test]=np.bincount(truth[train],minlength=k).argmax()
            selection.append({'fold':fold,'C':strength,'validation_macro_f1':score,'iterations':classifier.n_iter_.tolist(),
                              'iteration_limit_reached':bool((classifier.n_iter_>=5000).any()),'train_only_pca_whiten':True})
        models['direct_frozen_CNN_zone_classifier']=chosen_class
        models['training_prior']=prior
        models['uniform_random_seed42']=np.random.default_rng(42).integers(k,size=len(rows))
        for name in source['models']:
            pred=np.array([by_id[r['id']]['models'][name] for r in rows])
            models[name+':direct_head']=labeler(pred[:,3:5])
            rays=[]
            for r,p in zip(rows,pred):
                try:
                    xy=intersect_gaze(p[5:8]*1000,p[:3],r['calibration'])['screen_xy_px']
                    rays.append(np.array(xy)/r['screen_size_px'])
                except ValueError:rays.append([float('nan')]*2)
            models[name+':predicted_origin_ray']=labeler(np.array(rays))
        scores={name:{'overall':classification_scores(truth,p,k),
                      'per_subject':{s:classification_scores(truth[subjects==s],p[subjects==s],k) for s in sorted(set(subjects))}}
                for name,p in models.items()}
        paired={}
        ordered_subjects=sorted(set(subjects))
        for metric in ['macro_f1','balanced_accuracy','accuracy']:
            paired[metric]=paired_subject_delta(
                [scores['direct_frozen_CNN_zone_classifier']['per_subject'][s][metric] for s in ordered_subjects],
                [scores['training_prior']['per_subject'][s][metric] for s in ordered_subjects])
        result['tasks'][task]={'classes':k,'uniform_expected_accuracy':1/k,'classifier_inner_selection':selection,'models':scores,
                              'paired_subject_classifier_minus_prior':paired,'positive_delta_means_better':True}
        result['tasks'][task]['paired_subject_models_minus_prior']={
            name:{metric:paired_subject_delta([v['per_subject'][s][metric] for s in ordered_subjects],
                       [scores['training_prior']['per_subject'][s][metric] for s in ordered_subjects])
                  for metric in ['macro_f1','balanced_accuracy','accuracy']}
            for name,v in scores.items() if name!='training_prior'}
        raw_pred[task]={'true':truth,'predictions':models}
        print('coarse',task,'CNN F1',round(scores['direct_frozen_CNN_zone_classifier']['overall']['macro_f1'],3),flush=True)
    # Independent appearance -> estimated annotation pose and distance proxy. No oracle pose input.
    y=np.array([list(r['head_rvec'])+(np.array(r['head_translation_mm'])/1000).tolist()+[r['face_camera_distance_proxy_mm']/1000] for r in rows])
    pred=np.zeros_like(y);mean=np.zeros_like(y);aux_logs=[]
    for fold,(train,val,test) in enumerate(splits):
        target_scaler=StandardScaler().fit(y[train]);normalized=target_scaler.transform(y);normalized[test]=np.nan
        p,log=fit_ridge_probe(appearance,normalized,train,val,test,1536,validation_gaze=False)
        pred[test]=target_scaler.inverse_transform(p);mean[test]=y[train].mean(0);aux_logs.append({'fold':fold,**log})
    pose_scores={}
    for name,p in [('appearance_pose_distance',pred),('training_mean',mean)]:
        truth_angles=Rotation.from_rotvec(y[:,:3]).as_euler('yxz',degrees=True)[:,:2]
        estimated=Rotation.from_rotvec(p[:,:3]).as_euler('yxz',degrees=True)[:,:2]
        delta=np.abs((estimated-truth_angles+180)%360-180)
        geodesic=np.degrees((Rotation.from_rotvec(p[:,:3]).inv()*Rotation.from_rotvec(y[:,:3])).magnitude())
        distance=abs(p[:,-1]-y[:,-1])*1000
        pose_scores[name]={'yaw_mae_deg':float(delta[:,0].mean()),'pitch_mae_deg':float(delta[:,1].mean()),
                          'rotation_geodesic_mean_deg':float(geodesic.mean()),'face_camera_proxy_mae_mm':float(distance.mean()),
                          'per_subject':{s:{'yaw_mae_deg':float(delta[subjects==s,0].mean()),'pitch_mae_deg':float(delta[subjects==s,1].mean()),
                                            'distance_proxy_mae_mm':float(distance[subjects==s].mean())} for s in sorted(set(subjects))}}
    statuses=[camera_status(r) for r in rows]
    result['auxiliary_pose_distance']={'metrics':pose_scores,'training_logs':aux_logs,
        'yaw_pitch_definition':'extrinsic Euler y-x-z, degrees, first two components; compare to supplied estimated pose, not independent motion capture',
        'distance_definition':'norm of annotated estimated face center, static camera-distance proxy; not phone-eye GT or distance change'}
    result['auxiliary_pose_distance']['paired_subject_prediction_minus_mean']={
        key:paired_subject_delta([pose_scores['appearance_pose_distance']['per_subject'][s][key] for s in sorted(set(subjects))],
                                 [pose_scores['training_mean']['per_subject'][s][key] for s in sorted(set(subjects))])
        for key in ['yaw_mae_deg','pitch_mae_deg','distance_proxy_mae_mm']}
    result['camera_failure_detection']={'statuses':{k:statuses.count(k) for k in sorted(set(statuses))},
        'independently_annotated_missing_positive_examples':0,'sensitivity':None,'specificity':None,
        'interpretation':'structural IO/constant-image/landmark checks only. Natural failure detection accuracy cannot be validated without labeled failures.'}
    write_json(output/'coarse_results.json',result)
    write_jsonl(output/'coarse_predictions.jsonl',[{'id':r['id'],'subject_id':r['subject_id'],'status':statuses[i],
        'predicted_head_rvec':pred[i,:3].tolist(),'predicted_distance_proxy_mm':float(pred[i,-1]*1000),
        'tasks':{task:{'true':int(v['true'][i]),'models':{name:int(p[i]) for name,p in v['predictions'].items()}} for task,v in raw_pred.items()}}
        for i,r in enumerate(rows)])
    from .visualize_mpii import pyplot
    plt=pyplot();fig,ax=plt.subplots(figsize=(11,5),constrained_layout=True)
    selected=['direct_frozen_CNN_zone_classifier','training_prior','finetuned_layer4_n1:direct_head']
    selected=[s for s in selected if s in result['tasks']['2x2']['models']]
    for j,name in enumerate(selected):
        ax.bar(np.arange(4)+j*.25,[result['tasks'][t]['models'][name]['overall']['macro_f1'] for t in specs],width=.25,label=name)
    ax.set_xticks(np.arange(4)+.25,list(specs));ax.set_ylim(0,1);ax.set_ylabel('Macro-F1 (fixed label universe)');ax.legend(fontsize=7)
    output.mkdir(exist_ok=True,parents=True);fig.savefig(output/'zone_comparison.png',dpi=150);plt.close(fig)
    # Keep the same participants visible for point accuracy and coarse localization.
    names=['frozen_resnet18_224_face_eye_ridge','finetuned_layer4_n1']
    names=[n for n in names if n in source['models']]
    fig,axes=plt.subplots(2,1,figsize=(12,7),constrained_layout=True)
    ordered=sorted(set(subjects));x=np.arange(len(ordered))
    for name in names:
        axes[0].plot(x,[source['models'][name]['per_subject'][s]['screen_direct_error_mm']['mean'] for s in ordered],marker='o',label=name)
        task=result['tasks']['2x2']['models'][name+':direct_head']
        axes[1].plot(x,[task['per_subject'][s]['accuracy'] for s in ordered],marker='o',label=name)
    axes[1].axhline(.25,color='gray',ls='--',label='uniform expected 2x2 accuracy')
    axes[0].set_ylabel('Point error [mm]');axes[1].set_ylabel('2x2 zone accuracy');axes[1].set_ylim(0,1)
    for ax in axes:ax.set_xticks(x,ordered);ax.legend(fontsize=7)
    fig.savefig(output/'point_zone_subjects.png',dpi=150);plt.close(fig)
    return {'report':str(output/'coarse_results.json'),'tasks':list(specs),'natural_failure_sensitivity':None}
