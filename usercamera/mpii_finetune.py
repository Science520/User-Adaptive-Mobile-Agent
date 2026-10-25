"""Nested-participant partial fine-tuning, with architecture-matched frozen control.

Stem through layer3 is frozen and cached. Layer4 + a small shared face/eye head
is trainable; BN statistics are frozen. No gaze-trained external checkpoint.
"""
import copy
import json
import time
from pathlib import Path

import numpy as np

from .io import sha256,write_json
from .mpii_models import WEIGHTS_NAME,crop_boxes
from .mpii_protocol import target_matrix


def prepare_stem(rows,root,resolution=64):
    import torch
    from torchvision.models import resnet18
    from torchvision import transforms
    from PIL import Image
    root=Path(root);path=root/'cache/mpii_next'/f'stem_{resolution}.npz'
    weights=root/'cache/torch/hub/checkpoints'/WEIGHTS_NAME
    if not weights.exists():raise ValueError('Existing ImageNet weights required; no implicit download')
    fingerprint={'resolution':resolution,'weights_sha256':sha256(weights),'schema':'fixed-resize-normalize-stem-v1',
                 'samples':[{'id':r['id'],'sha256':sha256(r['image_path']),'boxes':crop_boxes(r)} for r in rows]}
    metadata=path.with_suffix('.json')
    torch.set_num_threads(4)
    base=resnet18(weights=None);base.load_state_dict(torch.load(weights,map_location='cpu',weights_only=True));base.eval()
    if path.exists() and metadata.exists():
        saved=json.loads(metadata.read_text())
        if saved.get('fingerprint')==fingerprint and saved.get('sha256')==sha256(path):
            with np.load(path,allow_pickle=False) as f:maps=f['maps'];frozen=f['frozen']
            return torch.from_numpy(maps),torch.from_numpy(frozen),base,saved
    stem=torch.nn.Sequential(base.conv1,base.bn1,base.relu,base.maxpool,base.layer1,base.layer2,base.layer3).eval()
    transform=transforms.Compose([transforms.Resize((resolution,resolution)),transforms.ToTensor(),
                                  transforms.Normalize([.485,.456,.406],[.229,.224,.225])])
    maps=[];features=[]
    with torch.inference_mode():
        for start in range(0,len(rows),12):
            batch=[]
            for r in rows[start:start+12]:
                with Image.open(r['image_path']) as image:
                    image=image.convert('RGB');batch.extend(transform(image.crop(b)) for b in crop_boxes(r))
            value=stem(torch.stack(batch));z=base.avgpool(base.layer4(value)).flatten(1)
            maps.append(value.numpy().reshape(-1,3,*value.shape[1:]));features.append(z.numpy().reshape(-1,1536))
    maps=np.concatenate(maps);frozen=np.concatenate(features)
    path.parent.mkdir(parents=True,exist_ok=True);np.savez_compressed(path,maps=maps,frozen=frozen)
    saved={'fingerprint':fingerprint,'sha256':sha256(path),'note':'cached ImageNet stem, no MPII target information'}
    write_json(metadata,saved)
    return torch.from_numpy(maps),torch.from_numpy(frozen),base,saved


def subset_training(rows,train,fraction,seed=42):
    rng=np.random.default_rng(seed);selected=[]
    for subject in sorted({rows[i]['subject_id'] for i in train}):
        group=np.array([i for i in train if rows[i]['subject_id']==subject])
        group=rng.permutation(group);selected.extend(group[:max(1,int(len(group)*fraction))])
    return np.asarray(sorted(selected),int)


def train_one(maps,embeddings,base,target,train,val,test,config,finetune,max_epochs=12,patience=3,seed=42):
    import torch
    from torch import nn
    torch.manual_seed(seed);torch.set_num_threads(4)
    class Network(nn.Module):
        def __init__(self):
            super().__init__()
            self.tail=copy.deepcopy(base.layer4) if finetune else nn.Identity()
            self.head=nn.Sequential(nn.Linear(1536,128),nn.ReLU(),nn.Linear(128,8))
            nn.init.normal_(self.head[-1].weight,std=.001)
            with torch.no_grad():self.head[-1].bias.copy_(target[train].mean(0))
        def forward(self,x):
            if finetune:
                x=self.tail(x.reshape(-1,*x.shape[2:])).mean((-1,-2)).reshape(-1,1536)
            return self.head(x)
    model=Network();data=maps if finetune else embeddings
    optimizer=torch.optim.AdamW(model.parameters(),lr=config['lr'],weight_decay=config['weight_decay'])
    best=None;best_score=float('inf');bad=0;history=[];rng=np.random.default_rng(seed)
    started=time.perf_counter()
    def evaluate(indices):
        model.eval()
        with torch.no_grad():return torch.cat([model(data[part]) for part in np.array_split(indices,max(1,int(np.ceil(len(indices)/32))))])
    for epoch in range(max_epochs):
        model.train()
        for module in model.modules():
            if isinstance(module,nn.BatchNorm2d):module.eval()
        permutation=rng.permutation(train);losses=[]
        for start in range(0,len(train),32):
            idx=permutation[start:start+32];p=model(data[idx]);y=target[idx]
            angular=(1-nn.functional.cosine_similarity(p[:,:3],y[:,:3],dim=1)).mean()
            screen=nn.functional.mse_loss(p[:,3:5],y[:,3:5]);origin=nn.functional.mse_loss(p[:,5:8],y[:,5:8])
            loss=angular+.2*screen+10*origin
            optimizer.zero_grad();loss.backward();nn.utils.clip_grad_norm_(model.parameters(),5);optimizer.step();losses.append(float(loss.detach()))
        pv=evaluate(val)
        cosine=nn.functional.cosine_similarity(pv[:,:3],target[val,:3],dim=1).clamp(-1,1)
        score=float(torch.rad2deg(torch.acos(cosine)).mean())
        history.append({'epoch':epoch+1,'train_loss':float(np.mean(losses)),'validation_angular_deg':score})
        if np.isfinite(score) and score<best_score-1e-5:
            best_score=score;best={'epoch':epoch+1,'state':copy.deepcopy(model.state_dict())};bad=0
        else:bad+=1
        if bad>=patience:break
    if best is None:raise ValueError('No finite validation checkpoint')
    model.load_state_dict(best['state']);pred=evaluate(test).numpy()
    # Batch-one model-only latency excludes decoding/cropping and the cached stem.
    model.eval()
    with torch.inference_mode():
        for _ in range(3):model(data[test[:1]])
        tick=time.perf_counter()
        for _ in range(10):model(data[test[:1]])
        ms=(time.perf_counter()-tick)*100
    return pred,{'config':config,'best_epoch':best['epoch'],'validation_angular_deg':best_score,'history':history,
                 'training_seconds':time.perf_counter()-started,'trainable_parameters':sum(p.numel() for p in model.parameters() if p.requires_grad),
                 'cached_tail_head_batch1_ms':ms,'inference_scope':'CPU cached maps/embeddings only, not end-to-end camera pipeline'}


def fine_tune_loso(rows,splits,root,output,max_epochs=12,fractions=(.5,1.0),resolution=64):
    import torch
    maps,embeddings,base,source=prepare_stem(rows,root,resolution)
    y=torch.tensor(target_matrix(rows),dtype=torch.float32)
    output=Path(output);predictions={};logs={}
    configs=[{'lr':1e-4,'weight_decay':1e-4},{'lr':3e-4,'weight_decay':1e-3}]
    for finetune in (False,True):
        for fraction in fractions:
            name=('finetuned_layer4' if finetune else 'matched_frozen_head')+f'_n{fraction:g}'
            predictions[name]=np.zeros((len(rows),8));logs[name]=[]
            for fold,(train,val,test) in enumerate(splits):
                train=subset_training(rows,train,fraction)
                cache=output/'folds'/name/f'fold_{fold:02d}.json'
                signature={'schema':'tail4-angular-screen-origin-v1','code_sha256':sha256(__file__),
                           'stem_sha256':source['sha256'],'train_ids':[rows[i]['id'] for i in train],
                           'val_ids':[rows[i]['id'] for i in val],'test_ids':[rows[i]['id'] for i in test],
                           'targets_train_val_sha256':__import__('hashlib').sha256(np.asarray(y[np.r_[train,val]]).tobytes()).hexdigest(),
                           'configs':configs,'max_epochs':max_epochs,'patience':3,'seed':42,'resolution':resolution}
                if cache.exists() and json.loads(cache.read_text()).get('signature')==signature:
                    saved=json.loads(cache.read_text());predictions[name][test]=saved['predictions'];logs[name].append(saved);continue
                candidates=[]
                for config in configs:
                    # No test labels are passed to the training function.
                    masked_target=y.clone();masked_target[test]=float('nan')
                    pred,log=train_one(maps,embeddings,base,masked_target,train,val,test,config,finetune,max_epochs)
                    candidates.append((pred,log))
                chosen=min(range(len(candidates)),key=lambda k:candidates[k][1]['validation_angular_deg'])
                pred,selected=candidates[chosen]
                saved={'signature':signature,'fold':fold,'selected_candidate':chosen,'selected':selected,
                       'candidates':[c[1] for c in candidates],'predictions':pred.tolist(),
                       'oracle_conditions':'supplied landmark crops; no pose input; known hardware for projection only',
                       'loss':'1-cosine(direction) + .2*MSE(screen_uv) + 10*MSE(origin_m); no geometry loss'}
                write_json(cache,saved);predictions[name][test]=pred;logs[name].append(saved)
                print(name,'fold',fold+1,'/',len(splits),'train',len(train),'epoch',selected['best_epoch'],
                      'val_deg',round(selected['validation_angular_deg'],3),flush=True)
    return predictions,logs,{'source':source,'architecture':'shared ImageNet ResNet18 stem+layer4, three annotated face/eye crops; 1536->128->8 head',
                             'resolution':resolution,'finetuning':'layer4 and head only; stem and all BN running statistics frozen',
                             'full_backbone_parameters':sum(p.numel() for p in base.parameters()),'user_specific_gaze_calibration':False,
                             'predicted_landmark_crops':False,'hardware_calibration':'known for converting output rays, never user-specific gaze points'}
