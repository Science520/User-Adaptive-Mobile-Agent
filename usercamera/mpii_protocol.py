"""Versioned LOSO splits shared by cleaning, gaze training and coarse tasks."""
import json
from pathlib import Path
import numpy as np
from .io import read_jsonl,sha256,write_json
from .mpii_models import prediction_errors


def load_samples(root):
    rows=read_jsonl(Path(root)/'processed/mpii.jsonl')
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('Duplicate samples')
    return rows


def make_splits(rows):
    subjects=sorted({r['subject_id'] for r in rows});splits=[]
    if len(subjects)<3:raise ValueError('Need at least three disjoint participants')
    for i,subject in enumerate(subjects):
        validation=subjects[(i+1)%len(subjects)]
        splits.append({'fold':i,'test_subject':subject,'validation_subject':validation,
                       'train_ids':[r['id'] for r in rows if r['subject_id'] not in (subject,validation)],
                       'validation_ids':[r['id'] for r in rows if r['subject_id']==validation],
                       'test_ids':[r['id'] for r in rows if r['subject_id']==subject]})
    return splits


def shared_splits(root='data',path='reports/mpii_next/splits.json'):
    rows=load_samples(root);splits=make_splits(rows)
    obj={'schema':'loso-inner-participant-v1','source_sha256':sha256(Path(root)/'processed/mpii.jsonl'),
         'protocol':'LOSO test=1 subject; next subject validation; other 13 training. No refit with validation labels.',
         'seed':42,'splits':splits}
    path=Path(path)
    if path.exists() and json.loads(path.read_text())!=obj:raise ValueError('Existing split differs: use new split file/version')
    write_json(path,obj)
    index={r['id']:i for i,r in enumerate(rows)}
    arrays=[tuple(np.asarray([index[x] for x in fold[key]],int) for key in ['train_ids','validation_ids','test_ids']) for fold in splits]
    for train,val,test in arrays:
        groups=[{rows[i]['subject_id'] for i in a} for a in (train,val,test)]
        assert not(groups[0]&groups[1] or groups[0]&groups[2] or groups[1]&groups[2])
    return rows,arrays,obj


def target_matrix(rows):
    return np.array([list(r['gaze_direction'])+(np.asarray(r['gaze_screen_px'])/r['screen_size_px']).tolist()
                     +(np.asarray(r['face_center_mm'])/1000).tolist() for r in rows])


def summarize_predictions(pred,rows):
    metrics,samples=prediction_errors(pred,rows)
    metrics['angular_error_deg']['p90']=float(np.quantile([r['angular_error_deg'] for r in samples],.9))
    for name in ['predicted_origin_ray','annotated_origin_ray']:
        valid=[r[name] for r in samples if r[name]['valid']]
        # Fixed deployment-style penalty: one screen diagonal per failed ray. Retain raw failures too.
        penalties_mm=[];penalties_px=[];gaps=[]
        for row,sample in zip(rows,samples):
            ray=sample[name];s=row['calibration']['screen']
            penalties_mm.append(ray['error_mm'] if ray['valid'] else float(np.hypot(s['width_mm'],s['height_mm'])))
            penalties_px.append(ray['error_px'] if ray['valid'] else float(np.hypot(*row['screen_size_px'])))
            if ray['valid'] and name=='predicted_origin_ray':
                delta=np.array(ray['screen_px'])-sample['screen_direct_px'];gaps.append(float(np.linalg.norm(delta)))
        metrics[name]['failure_penalty_rule']='one display diagonal per invalid ray; large valid errors are NOT clipped'
        metrics[name]['mean_error_mm_all_with_failure_penalty']=float(np.mean(penalties_mm))
        metrics[name]['mean_error_px_all_with_failure_penalty']=float(np.mean(penalties_px))
        metrics[name]['unconditional_raw_mean_error_px']=float(np.mean(penalties_px)) if len(valid)==len(rows) else None
        on_screen=sum(sample[name]['valid'] and bool((np.asarray(sample[name]['screen_px'])>=0).all() and
                       (np.asarray(sample[name]['screen_px'])<=row['screen_size_px']).all()) for row,sample in zip(rows,samples))
        metrics[name]['on_screen_intersection_count']=on_screen
        metrics[name]['on_screen_fraction_of_all']=on_screen/len(rows)
        metrics[name]['ray_direct_gap_px_valid_only']=float(np.mean(gaps)) if gaps else None
    return metrics,samples


def paired_subject_delta(left,right):
    delta=np.asarray(left)-np.asarray(right);rng=np.random.default_rng(42)
    b=delta[rng.integers(len(delta),size=(2000,len(delta)))].mean(axis=1)
    return {'mean_left_minus_right':float(delta.mean()),'ci95':np.quantile(b,[.025,.975]).tolist(),
            'note':'paired participant bootstrap of fixed OOF predictions, descriptive; no retraining inside bootstrap'}
