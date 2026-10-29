"""Matched contrasts; repeated targets create carryover, so randomization is not efficacy proof."""
from copy import deepcopy
from pathlib import Path
import hashlib,json
from .pilot_stimuli import build_protocol,template_hash,validate_trial
from .geometry import contrast_ratio


def build_protocol_v2(seed=42):
    old=build_protocol(seed,2)
    trials=[deepcopy(t) for t in old['trials'] if t['task']=='fixation']
    bases=[t for t in old['trials'] if t['task']=='visual_search' and len(t['elements'])==24]
    for block,base in enumerate(bases[:4]):
        for factor,conditions in [('font',['standard','large']),('position',['original','swapped']),('contrast',['standard','low']),('assistance',['none','highlight','zoom'])]:
            for condition in conditions:
                t=deepcopy(base); t.update(pair_id=f'b{block}_{factor}',condition_id=condition,randomization_seed=seed,block_id=block,
                    initial_assistance=condition if factor=='assistance' else 'none',matched_factor=factor)
                for e in t['elements']:
                    e['font_glyph_height_px']=28 if factor=='font' and condition=='large' else 20
                    e['foreground_gray']=175 if factor=='contrast' and condition=='low' else 35
                    e['visual_contrast']=contrast_ratio(e['foreground_gray'],255)
                if factor=='position' and condition=='swapped':
                    target=next(e for e in t['elements'] if e['element_id']==t['target_element_id'])
                    other=t['elements'][0] if target is not t['elements'][0] else t['elements'][-1]
                    for key in ['bounding_box_px','clickable_region_px']:
                        target[key],other[key]=other[key],target[key]
                t['conditions']={'matched_factor':factor,'condition_id':condition,'element_count':24,
                    'glyph_height_px':t['elements'][0]['font_glyph_height_px'],
                    'contrast_ratio':t['elements'][0]['visual_contrast'],
                    'domain':t['page_id'],'carryover_risk':'repeated_content_and_target'}
                t['trial_id']=f'B_v2_{len(trials):03d}';t['template_id']=template_hash(t);validate_trial(t);trials.append(t)
    return {'schema_version':'temporal-pilot-v2','seed':seed,'trials':trials,
            'design_note':'Within-pair only named factor changes; repeated content/targets have carryover. Counterbalance order; no efficacy claim from within-trial help.'}


if __name__=='__main__':
    out=Path('mobile_pilot/app/src/main/assets/protocol_v2.json')
    out.write_text(json.dumps(build_protocol_v2(),ensure_ascii=False,indent=2))
