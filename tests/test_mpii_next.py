import copy
import csv
import json
import numpy as np
import pytest
from PIL import Image

from test_mpii_geometry import make_sample
from usercamera.mpii_outlier_audit import boundary_status,view_ids,raw_annotations,audit_outliers
from usercamera.mpii_protocol import make_splits,summarize_predictions,target_matrix,shared_splits
from usercamera.mpii_strong import fit_ridge_probe,crossfit_pose
from usercamera.mpii_coarse import zone_labels,region_labels,classification_scores,camera_status
from usercamera.mpii_cleaning import download_expansion,expansion_plan
from usercamera.io import write_jsonl


def test_closed_display_vs_pixel_centers_and_fractional_boundaries():
    assert boundary_status([100,80],[100,80])['on_screen']
    b=boundary_status([100,80],[100,80],True)
    assert b['outside_axes']==['x','y']
    assert b['nearest_boundary_distance_px']==pytest.approx(np.sqrt(2))
    assert boundary_status([0,0],[100,80])['on_exact_boundary']
    assert not boundary_status([0,81],[100,80])['on_exact_boundary']
    assert not boundary_status([-.5,30],[100,80])['on_screen']
    # The external script's integer truncation would lose this fractional outlier.
    assert int(-.5)==0
    b=boundary_status([-3,84],[100,80])
    assert b['signed_axis_excess_px']==[-3,4]
    assert b['nearest_boundary_distance_px']==5
    assert b['signed_nearest_margin_px']==-4
    with pytest.raises(ValueError):boundary_status([np.nan,4],[100,80])


def test_day_filter_is_subject_day_not_day_number_and_keeps_ids():
    rows=[{'id':str(i),'subject_id':s,'day':d,'gaze_screen_px':xy,'screen_size_px':[100,80]}
          for i,(s,d,xy) in enumerate([('p00','day01',[-2,20]),('p00','day01',[20,20]),
                                       ('p01','day01',[20,20]),('p00','day02',[100,80])])]
    old=copy.deepcopy(rows);v=view_ids(rows)
    assert v=={'Original':['0','1','2','3'],'On-screen':['1','2','3'],'Day-filtered':['2','3']}
    assert rows==old


def test_raw_audit_records_consistent_outside_and_aggregates_day(tmp_path):
    from usercamera.camera_screen_geometry import screen_to_camera,px_to_mm
    row=make_sample(tmp_path);txt=tmp_path/'raw/mpiifacegaze/Data/p00/p00.txt'
    fields=txt.read_text().split();fields[0]='day02/0002.jpg';fields[1]='2100'
    target=screen_to_camera([*px_to_mm([2100,300],row['calibration']),0],row['calibration'])
    fields[24:27]=[str(x) for x in target]
    txt.write_text(txt.read_text()+' '.join(fields)+'\n')
    reference=tmp_path/'audit/reference/published_mpiifacegaze_not_on_screen.csv'
    reference.parent.mkdir(parents=True)
    with reference.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['file_name','on_screen_gaze_position','monitor_pixels']);w.writeheader()
        w.writerow({'file_name':'p00/day02/0002.jpg','on_screen_gaze_position':'[2100, 300]','monitor_pixels':'[1920, 1200]'})
    before=txt.read_bytes();a=audit_outliers(tmp_path,tmp_path/'audit')
    assert a['outside_n']==1 and a['subjects']['p00']['bad_days'][0]['day']=='day02'
    outside=json.loads((tmp_path/'audit/outliers.jsonl').read_text())
    assert outside['geometry_reconstruction_consistent']
    assert a['pperle']['published_csv']['same_ids']
    assert a['pperle']['published_csv']['coordinate_or_size_mismatch_ids']==[]
    assert not outside['image_locally_available']
    assert txt.read_bytes()==before


def test_loso_inner_groups_and_immutable_shared_manifest(tmp_path):
    rows=[{'id':f'{s}/{i}','subject_id':s} for s in ['p00','p01','p02','p03'] for i in range(2)]
    folds=make_splits(rows);lookup={r['id']:r['subject_id'] for r in rows}
    for fold in folds:
        groups=[{lookup[x] for x in fold[k]} for k in ['train_ids','validation_ids','test_ids']]
        assert not(groups[0]&groups[1] or groups[0]&groups[2] or groups[1]&groups[2])
    assert sorted(x for f in folds for x in f['test_ids'])==sorted(lookup)
    write_jsonl(tmp_path/'processed/mpii.jsonl',rows)
    path=tmp_path/'split.json';shared_splits(tmp_path,path)
    rows[0]['id']='changed';write_jsonl(tmp_path/'processed/mpii.jsonl',rows)
    with pytest.raises(ValueError,match='Existing split differs'):shared_splits(tmp_path,path)


def test_nested_ridge_test_targets_and_test_distribution_do_not_fit_preprocessing():
    rng=np.random.default_rng(1);x=rng.normal(size=(18,40));y=rng.normal(size=(18,8))
    train,val,test=np.arange(10),np.arange(10,14),np.arange(14,18)
    a,log=fit_ridge_probe(x,y,train,val,test,32)
    y[test]=np.nan;x[-1]=1e10
    b,log2=fit_ridge_probe(x,y,train,val,test,32)
    np.testing.assert_allclose(a[0],b[0])
    assert log['alpha']==log2['alpha']
    with pytest.raises(ValueError,match='Overlapping'):fit_ridge_probe(x,y,train,val,train,32)


def test_predicted_origin_projection_consistency_and_failed_rays_not_dropped(tmp_path):
    row=make_sample(tmp_path);pred=target_matrix([row])
    metrics,_=summarize_predictions(pred,[row])
    assert metrics['predicted_origin_ray']['coverage']==1
    assert metrics['predicted_origin_ray']['on_screen_intersection_count']==1
    assert metrics['predicted_origin_ray']['ray_direct_gap_px_valid_only']<1e-8
    row2=copy.deepcopy(row);row2['face_center_mm']=[1e9]*3
    # Predicted-origin projection cannot read the official origin at evaluation time.
    m2,_=summarize_predictions(pred,[row2])
    assert m2['predicted_origin_ray']==metrics['predicted_origin_ray']
    from usercamera.camera_screen_geometry import px_to_mm,screen_to_camera
    outside=pred.copy();uv=[1.2,.5]
    point=screen_to_camera([*px_to_mm(np.asarray(uv)*row['screen_size_px'],row['calibration']),0],row['calibration'])
    outside[0,:3]=point-row['face_center_mm'];outside[0,3:5]=uv
    offscreen,_=summarize_predictions(outside,[row])
    assert offscreen['predicted_origin_ray']['coverage']==1
    assert offscreen['predicted_origin_ray']['on_screen_intersection_count']==0
    assert offscreen['predicted_origin_ray']['ray_direct_gap_px_valid_only']<1e-8
    pred[:,:3]=0
    failed,_=summarize_predictions(pred,[row])
    ray=failed['predicted_origin_ray']
    assert ray['total']==1 and ray['invalid_count']==1
    assert ray['unconditional_raw_mean_error_px'] is None
    assert ray['mean_error_px_all_with_failure_penalty']==pytest.approx(np.hypot(*row['screen_size_px']))


def test_predicted_pose_stacking_does_not_read_heldout_pose(tmp_path):
    row=make_sample(tmp_path);rows=[]
    for i in range(12):
        r=copy.deepcopy(row);r['subject_id']=f'p{i//2:02d}';r['head_rvec']=[i*.01,.1,.2];rows.append(r)
    features=np.random.default_rng(42).normal(size=(12,40))
    train,val,test=np.arange(6),np.arange(6,8),np.arange(8,12)
    p=crossfit_pose(features,rows,train,val,test)
    for i in test:rows[i]['head_rvec']=[1e6]*3;rows[i]['head_translation_mm']=[1e9]*3
    second=crossfit_pose(features,rows,train,val,test)
    np.testing.assert_allclose(p,second)


def test_zone_closed_upper_edge_and_failures_count_wrong():
    uv=np.array([[0,0],[1,1],[.5,.5],[-.1,.5],[np.nan,.5]])
    assert zone_labels(uv,2).tolist()==[0,3,3,-1,-1]
    assert region_labels(uv).tolist()==[0,2,1,-1,-1]
    scores=classification_scores([0,1,2,-1],[0,-1,2,2],3)
    assert scores['n']==3 and scores['excluded_outside_true_target']==1
    assert scores['accuracy']==pytest.approx(2/3)
    assert scores['invalid_predictions_counted_wrong']==1
    assert scores['balanced_accuracy']==pytest.approx(2/3)


def test_structural_camera_failure_and_explicit_download_gate(tmp_path):
    row=make_sample(tmp_path)
    assert camera_status(row)=='constant_frame'
    row['image_path']=str(tmp_path/'absent.jpg')
    assert camera_status(row)=='missing_image'
    with pytest.raises(ValueError,match='Explicit --allow-download'):download_expansion(tmp_path,{},tmp_path/'expansion')
    (tmp_path/'expansion').mkdir()
    with pytest.raises(ValueError,match='never overwrite'):download_expansion(tmp_path,{},tmp_path/'expansion',allow_download=True)
    with pytest.raises(ValueError,match='nonnegative'):expansion_plan(tmp_path,-1)


def test_neural_trainer_never_reads_test_labels():
    import torch
    from usercamera.mpii_finetune import train_one
    torch.manual_seed(1)
    embeddings=torch.randn(9,1536);maps=torch.zeros(9,3,256,4,4)
    target=torch.randn(9,8);target[7:]=float('nan')
    pred,log=train_one(maps,embeddings,None,target,np.arange(5),np.arange(5,7),np.arange(7,9),
                       {'lr':1e-4,'weight_decay':1e-4},False,max_epochs=1)
    assert np.isfinite(pred).all() and pred.shape==(2,8)
    assert log['best_epoch']==1


def test_cli_new_commands_dispatch_without_touching_old_routes(monkeypatch):
    from usercamera.cli import main
    calls=[]
    monkeypatch.setattr('usercamera.mpii_outlier_audit.audit_outliers',lambda *a:calls.append(a) or {})
    assert main(['mpii-audit-outliers','--output','somewhere'])==0
    assert calls==[('data','somewhere')]
