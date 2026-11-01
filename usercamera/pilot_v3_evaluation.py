"""Small-model entry point with protocol, evidence, timing and independent-group guards."""
import json
from pathlib import Path
import numpy as np
from .io import read_jsonl,write_json
from .pilot_features import SCREEN_KEYS,ACTION_KEYS
from .pilot_temporal import split_windows,fit_tabular,fit_gru,probability_metrics


def readiness(rows,label):
    reasons=[];people={r['participant_id'] for r in rows};sessions={r['session_id'] for r in rows}
    versions={(r['protocol_version'],r.get('label_schema_version','legacy-unspecified')) for r in rows}
    if len(versions)!=1:reasons.append('mixed_task_or_label_protocols')
    if any(r.get('evidence_tier')!='real_device_recording' for r in rows):reasons.append('non_research_or_mixed_evidence')
    if any(not r.get('clock_alignment_usable',False) for r in rows):reasons.append('unverified_video_UI_touch_alignment')
    if len(people if len(people)>1 else sessions)<3:reasons.append('fewer_than_three_independent_train_validation_test_groups')
    observed=[r[label] for r in rows if r.get(label) is not None]
    if len(set(observed))<2:reasons.append('target_has_one_or_zero_classes_after_prefix_selection')
    return {'blockers':reasons,'participants':len(people),'sessions':len(sessions),'protocols':[list(v) for v in sorted(versions)],
            'scope':'participant-disjoint' if len(people)>1 else 'within-person/session-disjoint only','class_counts':{str(c):observed.count(c) for c in set(observed)}}


def evaluate_cached(private='reports/pilot_v3/private/cache_module_recheck',output='reports/pilot_v3/temporal/evaluation',prefix=2,recent=2,label='difficulty',algorithms=('logistic','hist_gradient_boosting','gru')):
    root=Path(private);dest=Path(output)/'results.json'
    if dest.exists():raise ValueError('Evaluation exists; preserve results and select a new output')
    if not algorithms or not set(algorithms)<={'logistic','hist_gradient_boosting','gru'}:raise ValueError('Unknown algorithms')
    target={'difficulty':'label_self_report_difficulty','future_help':'label_future_help'}[label]
    allrows=read_jsonl(root/'windows.jsonl');indices=[i for i,r in enumerate(allrows) if r['decision_prefix_s']==prefix and r['recent_window_s']==recent and r.get(target) is not None]
    rows=[allrows[i] for i in indices]
    if not rows:raise ValueError('No eligible windows at this prefix/recent setting')
    quality=readiness(rows,target);report={'status':'blocked' if quality['blockers'] else 'ready','readiness':quality,'target':label,'prefix_s':prefix,'recent_s':recent,'eligible_trials':len(rows),
        'no_help_is_not_no_difficulty':True,'models':{},'algorithms':list(algorithms),'one_window_per_trial':True,'metrics_claim_physical_sync_validated':False}
    for r in rows:
        if r['cutoff_ns']>=r['label_time_ns']:raise ValueError('Label not after input cutoff')
    if quality['blockers']:write_json(dest,report);return report
    # A future synchronized dataset can use these existing small train/validation-selected models.
    prepared=[{**r,'input_end_ns':r['cutoff_ns']} for r in rows];_,folds,scope=split_windows(prepared)
    if not folds:report.update(status='blocked',split_scope=scope);write_json(dest,report);return report
    with np.load(root/'training_cache.npz') as cache:
        appearance=cache['single_frame_gray16x16'][indices];seq=cache['sequence'];ts=cache['sequence_timestamps_ns'];offsets=cache['sequence_offsets'];user_names=cache['sequence_names'].tolist()
        user_keys=sorted(rows[0]['user'])
        def vals(mapping,keys):return [np.nan if mapping.get(k) is None else float(mapping[k]) for k in keys]
        screen=np.array([vals(r['screen'],SCREEN_KEYS) for r in rows]);touch=np.array([vals(r['touch_history'],ACTION_KEYS) for r in rows]);user=np.array([vals(r['user'],user_keys) for r in rows])
        matrices={'Screen':screen,'Screen_Touch':np.c_[screen,touch],'Single_Face':np.c_[screen,touch,appearance],'Temporal_User':np.c_[screen,touch,user]}
        sequences={}
        for model,x in matrices.items():
            steps=[]
            for j,i in enumerate(indices):
                start=allrows[i]['input_start_ns'];end=allrows[i]['cutoff_ns'];a,b=int(offsets[i]),int(offsets[i+1]);per=[]
                for edge in np.linspace(start,end,7)[1:]:
                    eligible=np.flatnonzero(ts[a:b]<edge)
                    # Only raw User history evolves; other summaries are available by final decision cutoff.
                    extra=seq[a+eligible[-1]] if len(eligible) else np.full(len(user_names),np.nan)
                    per.append(np.r_[screen[j],touch[j],extra] if model=='Temporal_User' else x[j])
                steps.append(per)
            sequences[model]=np.array(steps,float)
        y=np.array([r[target] for r in rows],int)
        for model,x in matrices.items():
            report['models'][model]={}
            for algorithm in algorithms:
                pred=[];truth=[];details=[]
                for train,val,test in folds:
                    p,info=fit_gru(sequences[model][train],y[train],sequences[model][val],y[val],sequences[model][test]) if algorithm=='gru' else fit_tabular(x[train],y[train],x[val],y[val],x[test],algorithm)
                    pred.extend(p);truth.extend(y[test]);details.append(info)
                report['models'][model][algorithm]={'metrics':probability_metrics(truth,pred),'fits':details}
    report.update(status='evaluated',split_scope=scope,limitation='Observational predictive comparison; not evidence of causal assistance benefit')
    write_json(dest,report);return report
