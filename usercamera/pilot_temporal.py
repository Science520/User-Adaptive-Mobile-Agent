"""Small grouped baselines on trial-resolved labels and causal replay prefixes."""
import json
from pathlib import Path
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score,f1_score,log_loss
from threadpoolctl import threadpool_limits
from .io import read_jsonl,write_json,write_jsonl,sha256
from .pilot_features import SCREEN_KEYS,ACTION_KEYS,USER_KEYS

MODALITIES={'M0':'S','M1':'SA','M2':'U','M3':'SU','M4':'SAU','M5':'SAU'}


def flatten(feature,modalities):
    values=[]
    for letter,key,names in [('S','screen',SCREEN_KEYS),('A','actions',ACTION_KEYS),('U','user',USER_KEYS)]:
        if letter in modalities:values.extend(feature[key].get(n) if feature[key].get(n) is not None else np.nan for n in names)
    return values


def split_windows(rows):
    if not rows:raise ValueError('No eligible windows')
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('Duplicate window IDs')
    if len({(r['session_id'],r['trial_id']) for r in rows})!=len(rows):raise ValueError('Do not mix multiple prefixes of the same trial in one evaluation')
    participants={r['participant_id'] for r in rows}
    group_by='participant_id' if len(participants)>1 else 'session_id'
    groups=sorted({r[group_by] for r in rows})
    if len(groups)<3:return group_by,[],{'status':'insufficient_groups','groups':len(groups),'required':3,'reason':'independent train/validation/test groups required'}
    folds=[]
    for k,test_group in enumerate(groups):
        validation_group=groups[(k+1)%len(groups)]
        test=np.array([i for i,r in enumerate(rows) if r[group_by]==test_group],int)
        val=np.array([i for i,r in enumerate(rows) if r[group_by]==validation_group],int)
        train=np.array([i for i,r in enumerate(rows) if r[group_by] not in [test_group,validation_group]],int)
        # Purge exact UI templates crossing partitions, even across distinct sessions/people.
        test_templates={rows[i]['template_id'] for i in test}
        val=val[[rows[i]['template_id'] not in test_templates for i in val]]
        heldout_templates=test_templates|{rows[i]['template_id'] for i in val}
        train=train[[rows[i]['template_id'] not in heldout_templates for i in train]]
        if not len(train) or not len(val):
            return group_by,[],{'status':'insufficient_after_template_purge','reason':'Repeated UI templates cross groups; create independently randomized session layouts','groups':len(groups)}
        folds.append((train,val,test))
    return group_by,folds,{'status':'ready','groups':len(groups),'inference_scope':'participant-disjoint' if group_by=='participant_id' else 'within-person feasibility, session-disjoint',
                         'exact_template_overlap_policy':'purge from train/validation when shared with heldout partitions'}


def mismatched_user(rows,indices):
    """Previous trial's prefix, within this partition/session only; no future donor."""
    lookup={};donors={}
    for i in sorted(indices,key=lambda i:rows[i]['input_start_ns']):
        r=rows[i];key=(r['participant_id'],r['session_id'])
        prior=lookup.get(key)
        if prior is not None and rows[prior]['input_end_ns']<=r['input_start_ns']:donors[i]=prior
        else:donors[i]=None
        lookup[key]=i
    return donors


def design_matrix(rows,indices,model):
    donors=mismatched_user(rows,indices) if model=='M5' else {i:i for i in indices}
    flat=[];sequence=[]
    for i in indices:
        r=rows[i];source=rows[donors[i]] if donors[i] is not None else None
        value={key:r[key] for key in ['screen','actions','user']}
        if model=='M5':value['user']=source['user'] if source else {k:None for k in USER_KEYS}
        flat.append(flatten(value,MODALITIES[model]));steps=[]
        for j,step in enumerate(r['sequence']):
            v={**step}
            if model=='M5':v['user']=source['sequence'][j]['user'] if source else {k:None for k in USER_KEYS}
            steps.append(flatten(v,MODALITIES[model]))
        sequence.append(steps)
    return np.asarray(flat,float),np.asarray(sequence,float),donors


def probability_metrics(y,p):
    y=np.asarray(y,int);p=np.clip(np.asarray(p,float),1e-7,1-1e-7);pred=(p>=.5).astype(int)
    bins=[];ece=0.
    for a,b in zip(np.linspace(0,1,6)[:-1],np.linspace(0,1,6)[1:]):
        m=(p>=a)&(p<(b if b<1 else 1.0001))
        if m.any():
            mean=float(p[m].mean());rate=float(y[m].mean());ece+=m.mean()*abs(mean-rate)
            bins.append({'n':int(m.sum()),'mean_predicted_probability':mean,'observed_positive_fraction':rate})
    recalls=[np.mean(pred[y==c]==c) for c in [0,1] if (y==c).any()]
    return {'n':len(y),'AUROC':float(roc_auc_score(y,p)) if len(set(y))==2 else None,
        'macro_f1':float(f1_score(y,pred,labels=[0,1],average='macro',zero_division=0)),
        'balanced_accuracy':float(np.mean(recalls)),'accuracy':float((pred==y).mean()),'brier_score':float(np.mean((p-y)**2)),
        'log_loss':float(log_loss(y,np.c_[1-p,p],labels=[0,1])),'ECE_5_equal_width_bins':float(ece),'calibration_bins':bins,
        'missing_positive_or_negative_class':len(set(y))<2}


def fit_tabular(a,y,b,yval,c,algorithm):
    if len(set(y))<2:return np.full(len(c),np.mean(y)),{'constant_training_prior':True}
    candidates=[]
    for value in ([.1,1.,10.] if algorithm=='logistic' else [7,15]):
        classifier=LogisticRegression(C=value,max_iter=2000,class_weight=None,random_state=42) if algorithm=='logistic' else HistGradientBoostingClassifier(max_leaf_nodes=value,max_iter=80,learning_rate=.08,early_stopping=False,random_state=42)
        model=make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True,add_indicator=True),StandardScaler(),classifier)
        model.fit(a,y);v=model.predict_proba(b)[:,1];score=float(np.mean((v-yval)**2));candidates.append((score,value,model))
    score,value,model=min(candidates,key=lambda t:t[0])
    return model.predict_proba(c)[:,1],{'validation_brier':score,'selected_C_or_max_leaf_nodes':value,'preprocessing':'training-only median imputation with missing indicators and standard scaling'}


def fit_gru(a,y,b,yval,c,max_epochs=20):
    import torch
    torch.set_num_threads(1);torch.manual_seed(42)
    if len(set(y))<2:return np.full(len(c),np.mean(y)),{'constant_training_prior':True}
    imputer=SimpleImputer(strategy='median',keep_empty_features=True,add_indicator=True);scaler=StandardScaler()
    aa=imputer.fit_transform(a.reshape(-1,a.shape[-1]));aa=scaler.fit_transform(aa)
    def transform(x):return torch.tensor(scaler.transform(imputer.transform(x.reshape(-1,x.shape[-1]))).reshape(len(x),x.shape[1],-1),dtype=torch.float32)
    aa=torch.tensor(aa.reshape(len(a),a.shape[1],-1),dtype=torch.float32);bb,cc=transform(b),transform(c)
    class Net(torch.nn.Module):
        def __init__(self):
            super().__init__();self.gru=torch.nn.GRU(aa.shape[-1],16,batch_first=True);self.head=torch.nn.Linear(16,1)
        def forward(self,x):return self.head(self.gru(x)[1][-1]).squeeze(-1)
    model=Net();opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.001);target=torch.tensor(y,dtype=torch.float32)
    best=None;best_score=float('inf');bad=0;history=[]
    for epoch in range(max_epochs):
        model.train();order=torch.randperm(len(a))
        for idx in order.split(16):
            loss=torch.nn.functional.binary_cross_entropy_with_logits(model(aa[idx]),target[idx]);opt.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);opt.step()
        model.eval()
        with torch.no_grad():p=torch.sigmoid(model(bb)).numpy()
        score=float(np.mean((p-yval)**2));history.append({'epoch':epoch+1,'validation_brier':score})
        if score<best_score-1e-6:
            best_score=score;best={k:v.detach().clone() for k,v in model.state_dict().items()};best_epoch=epoch+1;bad=0
        else:bad+=1
        if bad>=4:break
    model.load_state_dict(best);model.eval()
    with torch.no_grad():p=torch.sigmoid(model(cc)).numpy()
    return p,{'best_epoch':best_epoch,'history':history,'parameters':sum(p.numel() for p in model.parameters()),
        'architecture':'one layer GRU hidden16 -> binary logit, six causal cumulative time bins','validation_brier':best_score}


@threadpool_limits.wrap(limits=1,user_api='blas')
def evaluate_temporal(features='reports/pilot/features',output='reports/pilot',allow_mock=False,algorithms=('logistic','hist_gradient_boosting','gru')):
    if not algorithms or not set(algorithms)<={'logistic','hist_gradient_boosting','gru'}:raise ValueError('Unknown/empty algorithm selection')
    paths=sorted(Path(features).rglob('windows.jsonl'));all_rows=[r for p in paths for r in read_jsonl(p)]
    if not all_rows:raise ValueError('No extracted windows; run pilot-extract-features first')
    tiers={r['evidence_tier'] for r in all_rows}
    if len(tiers)!=1:raise ValueError('Never mix mock and real recordings in one result')
    if tiers=={'mock'} and not allow_mock:raise ValueError('Mock evaluation requires --allow-mock')
    if tiers!={'mock'} and any(not r['clock_alignment_usable'] and r['user']['camera_observed'] for r in all_rows):raise ValueError('Unvalidated camera clock mapping: fusion metrics blocked')
    for r in all_rows:
        if r['label_resolution']!='trial_only' or r['input_end_ns']>r['label_time_ns']:raise ValueError('Invalid causal label window')
        if r['difficulty_label_source']!=('mock_self_report_fixture' if tiers=={'mock'} else 'self_report'):raise ValueError('Untrusted difficulty provenance')
    result={'evidence_tier':next(iter(tiers)),'supports_real_H2':False,'supports_H3':False,'evaluation_modes':{},
            'label':'post-trial self_report rating >=3; binary target, not per-frame onset','source_sha256':{str(p):sha256(p) for p in paths},
            'M5':'replace User by previous trial prefix within same partition and session; first trial missing, no future donor',
            'uncertainty':'small diagnostic dataset; no significance claim or intervention benefit. Report fold metrics and missingness.',
            'input_features':{'S':SCREEN_KEYS,'A':ACTION_KEYS,'U':USER_KEYS},'algorithms':list(algorithms)}
    predictions=[];split_records=[]
    for mode in ['trial','prefix_1s','prefix_2s','prefix_3s']:
        rows=[r for r in all_rows if r['mode']==mode]
        if not rows:
            result['evaluation_modes'][mode]={'scope':{'status':'no_eligible_trials'},'n':0,'models':{}};continue
        group_by,folds,scope=split_windows(rows)
        result['evaluation_modes'][mode]={'scope':scope,'group_by':group_by,'n':len(rows),'models':{},
            'camera_missing_fraction':float(np.mean([1-r['user']['camera_observed'] for r in rows])) if rows else None}
        if not folds:continue
        y=np.array([r['difficulty'] for r in rows]);prior=np.zeros(len(rows))
        for fold,(train,val,test) in enumerate(folds):
            prior[test]=y[train].mean();split_records.append({'mode':mode,'fold':fold,'train_ids':[rows[i]['id'] for i in train],
                'validation_ids':[rows[i]['id'] for i in val],'test_ids':[rows[i]['id'] for i in test],
                'train_templates':sorted({rows[i]['template_id'] for i in train}),'validation_templates':sorted({rows[i]['template_id'] for i in val}),
                'test_templates':sorted({rows[i]['template_id'] for i in test})})
        result['evaluation_modes'][mode]['training_prior']=probability_metrics(y,prior)
        for model_name in MODALITIES:
            for algorithm in algorithms:
                p=np.zeros(len(rows));logs=[];donor_trace={}
                for fold,(train,val,test) in enumerate(folds):
                    parts=[design_matrix(rows,idx,model_name) for idx in [train,val,test]]
                    selected=1 if algorithm=='gru' else 0;a,b,c=[v[selected] for v in parts]
                    # Only train and validation labels reach fitting. Test targets are scored afterwards.
                    if algorithm=='gru':p[test],log=fit_gru(a,y[train],b,y[val],c)
                    else:p[test],log=fit_tabular(a,y[train],b,y[val],c,algorithm)
                    log.update(fold=fold,train_n=len(train),validation_n=len(val),test_n=len(test));logs.append(log)
                    for i,donor in parts[2][2].items():donor_trace[i]=rows[donor]['id'] if donor is not None else None
                key=model_name+':'+algorithm;groups=sorted({r[group_by] for r in rows})
                per_group={g:probability_metrics(y[[i for i,r in enumerate(rows) if r[group_by]==g]],p[[i for i,r in enumerate(rows) if r[group_by]==g]]) for g in groups}
                result['evaluation_modes'][mode]['models'][key]={'metrics':probability_metrics(y,p),'per_group':per_group,'training_logs':logs}
                predictions.extend({'id':r['id'],'mode':mode,'model':key,'p_difficulty':float(p[i]),'target':int(y[i]),'user_donor_window_id':donor_trace[i]} for i,r in enumerate(rows))
                print('temporal',mode,key,round(result['evaluation_modes'][mode]['models'][key]['metrics']['macro_f1'],3),flush=True)
    dest=Path(output);write_json(dest/'temporal_results.json',result);write_jsonl(dest/'temporal_predictions.jsonl',predictions)
    write_json(dest/'temporal_splits.json',{'source_sha256':result['source_sha256'],'splits':split_records,'seed':42,
        'policy':'participant groups if >1 participant; otherwise session groups; separate one-group internal validation; purge exact repeated templates'})
    return {'report':str(dest/'temporal_results.json'),'evidence_tier':result['evidence_tier'],'modes':{k:v['scope'] for k,v in result['evaluation_modes'].items()},'supports_real_H2':False}
