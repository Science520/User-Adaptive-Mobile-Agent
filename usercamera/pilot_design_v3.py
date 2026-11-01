"""R/S/M design with unique targets, reserved distractors and 16 counterbalance groups."""
import json,hashlib,random,math
from itertools import combinations
from difflib import SequenceMatcher
from copy import deepcopy
from pathlib import Path
from collections import Counter
from PIL import Image,ImageDraw,ImageFont
from .pilot_stimuli import VOCABULARY,validate_trial,template_hash,build_protocol
from .pilot_v3_audit import csv_write
from .geometry import contrast_ratio
from .synthetic import load_font

COLORS=[[234,243,255],[233,247,238],[255,241,226],[244,235,252]]
DOMAINS={**VOCABULARY,'community':'社区公告 活动报名 志愿服务 场地预约 物业报修 访客登记 邻里互助 失物招领 居委咨询 垃圾分类 养老服务 托育服务 社区食堂 停车管理 宠物登记 设施借用 快递代收 应急联系 健康讲座 便民热线 公共维修 意见反馈 电子门禁 文化活动'.split()}
EXTRA={'medical':['检查报告','就诊记录','挂号记录','门诊缴费'],'utilities':['发票查询','账单明细','户号查询','缴费申请']}
WILLIAMS=[[0,1,3,2],[1,2,0,3],[2,3,1,0],[3,0,2,1]]
ASSIST=['none','zoom_text','increase_contrast','highlight_region','highlight_target','enlarge_touch','explain']


def vocabulary():
    seen=set();rows=[]
    for domain,words in DOMAINS.items():
        for text in words+EXTRA.get(domain,[]):
            if text in seen:continue
            seen.add(text);group=next((k for k in ['报告','记录','预约','查询','申请','缴费','管理','服务'] if k in text),'other')
            rows.append({'target_id':f'{domain}_{len(rows):03d}','target_text':text,'domain':domain,'semantic_group':group})
    return rows


EXPLANATIONS={
 '乘车码':'乘坐公交或地铁时出示的电子凭证。','客服咨询':'联系服务人员询问问题。','浏览记录':'查看过去浏览过的商品或页面。',
 '出院小结':'汇总一次住院情况的文书入口。','付款码':'出示给商家扫描的付款码；本实验不付款。','设施借用':'申请临时使用社区公共设施。',
 '社区公告':'查看社区发布的通知。','手机充值':'为手机账户补充余额；本实验不充值。','服务网点':'查询可提供服务的线下地点。',
 '访客登记':'登记来访人员的信息。','电费缴纳':'查看或办理电费账单；本实验不缴费。','联系客服':'联系处理服务问题的工作人员。',
 '评价管理':'查看和管理提交过的评价。','包裹寄件':'办理寄送包裹的业务入口。','发票管理':'查看和管理发票。',
 '长途汽车':'查询城际或长途客车服务。','电子票券':'查看已经领取或购买的电子凭证。','养老服务':'查询面向老年人的生活支持服务。',
 '住址管理':'查看或修改保存的住址。','机场巴士':'查询往返机场的大巴服务。','医保结算':'查看医保费用结算服务；本实验不办理。',
 '实时公交':'查询公交车辆当前到站情况。','就诊指南':'查看就医流程和服务指引。','体检预约':'选择体检服务的预约入口；本实验不预约。'}

def relative_contrast(gray,bg):
    def lin(v):
        v=v/255.;return v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4
    lum=.2126*lin(bg[0])+.7152*lin(bg[1])+.0722*lin(bg[2]);l=lin(gray)
    return (max(l,lum)+.05)/(min(l,lum)+.05)


def quick_subset(trials):
    cells=sorted({t['condition_id'] for t in trials})
    def choose(i,selected,counts):
        if i==len(cells):return selected if all(counts.get(z,0)==2 for z in range(4)) else None
        pool=[t for t in trials if t['condition_id']==cells[i]]
        for pair in combinations(pool,2):
            new=Counter(counts);new.update(t['target_position']['zone_2x2'] for t in pair)
            if max(new.values())>2:continue
            found=choose(i+1,selected+list(pair),new)
            if found:return found
        return None
    chosen=choose(0,[],Counter())
    if not chosen:raise ValueError('Cannot balance quick subset')
    ids={t['trial_id'] for t in chosen}
    return [t for t in trials if t['trial_id'] in ids]

def build_protocol_v3(seed=42):
    vocab=vocabulary();rng=random.Random(seed);targets=[]
    # Fixed semantic families, independent of condition; rotate every target across conditions over groups.
    for domain in DOMAINS:
        pool=[r for r in vocab if r['domain']==domain];rng.shuffle(pool);targets.extend(pool[:4])
    rng.shuffle(targets);reserved={t['target_text'] for t in targets};plans={};balance=[]
    for group in range(16):
        trials=[]
        for index,target in enumerate(targets):
            cell=(index+group%4)%4;readability='hard' if cell in [1,3] else 'easy';load='high' if cell in [2,3] else 'low'
            task='readability' if load=='low' else 'mixed' if readability=='hard' else 'visual_search'
            zone=(index//4+index%4+group//4)%4;rr=random.Random(seed+index*719+group//4*137)
            perregion=6;slot=zone*6+(index%6);slots=list(range(24))
            core=[slot]
            for q in range(4):
                if q!=zone:core.append(q*6+(index+q)%6)
            core+=rr.sample([s for s in slots if s not in core],2)
            occupied=core if load=='low' else slots
            pool=[v for v in vocab if v['target_text'] not in reserved]
            pool.sort(key=lambda v:(-SequenceMatcher(None,v['target_text'],target['target_text']).ratio(),v['semantic_group']!=target['semantic_group'],v['domain']!=target['domain']))
            close=pool[:5];remaining=pool[5:];rr.shuffle(remaining)
            # Same six core choices/positions across low/high load, then add 18 choices.
            assignment=dict(zip(sorted(s for s in core if s!=slot),close))
            assignment.update(zip([s for s in slots if s!=slot and s not in assignment],remaining))
            elements=[];glyph=20 if readability=='hard' else 32
            for s in sorted(occupied):
                q=s//6;local=s%6;col=local%2;row=local//2
                qx=q%2;qy=q//2;x=50+qx*510+col*232;y=390+qy*670+row*180
                term=target if s==slot else assignment[s];role='target' if s==slot else 'distractor';box=[x,y,x+218,y+146]
                elements.append({'element_id':f'item_{s:02d}','text':term['target_text'],'text_lines':[term['target_text'][i:i+6] for i in range(0,len(term['target_text']),6)],
                    'bounding_box_px':box,'clickable_region_px':box,'font_glyph_height_px':glyph,'font_weight':400,
                    'role':role,'foreground_gray':35,'background_rgb':COLORS[q],'visual_contrast':relative_contrast(35,COLORS[q]),
                    'region_id':f'region_{q}','icon_id':f'icon_{local%3}','page_id':f'services_v3_{index}', 'navigation_transition':'task_complete' if role=='target' else None})
            target_element=next(e for e in elements if e['role']=='target')
            t={'trial_id':f'{"R" if task=="readability" else "S" if task=="visual_search" else "M"}_v3_{index:03d}',
                'task':task,'task_family':task,'page_id':f'services_v3_{index}','base_size_px':[1080,1920],
                'instruction':'请找到并点击「'+target['target_text']+'」','target_element_id':target_element['element_id'],
                'target_explanation':EXPLANATIONS.get(target['target_text'],'这是指定服务的模拟入口，本轮只进行查找。'),'target_id':target['target_id'],'target_text':target['target_text'],'domain':target['domain'],'semantic_group':target['semantic_group'],
                'distractor_pool':[e['text'] for e in elements if e['role']=='distractor'],'target_position':{'zone_2x2':zone,'slot':slot},
                'difficulty_manipulation':{'readability':readability,'search_load':load,'only_readability_manipulation':'glyph_height','actual_human_difficulty_label':False},
                'matched_condition_id':f'{target["domain"]}_{target["semantic_group"]}_len{len(target["target_text"])}_{load}_z{zone}',
                'pair_id':f'match_{target["domain"]}_{target["semantic_group"]}_len{len(target["target_text"])}','randomization_block_id':f'block_{index//4:02d}',
                'condition_id':f'{readability}_{load}','randomization_seed':seed,'counterbalance_group':group,
                'regions':[{'region_id':f'region_{q}','label':['常用服务','生活助手','便民业务','更多服务'][q],'box':[35+(q%2)*510,325+(q//2)*670,535+(q%2)*510,965+(q//2)*670],'background_rgb':COLORS[q]} for q in range(4)],
                'initial_assistance':'none','timeout_ms':30000,'correct_action_path':[target_element['element_id']],
                'conditions':{'readability':readability,'search_load':load,'glyph_height_px':glyph,'font_weight':400,'element_count':len(elements),
                    'color_scheme':'four_fixed_pastel_regions','text_similarity':'semantic_pool_matched_not_manipulated','viewing_condition':'not_measured_unless_external_measurement'},'elements':elements}
            t['template_id']=template_hash(t);validate_trial(t);trials.append(t)
        order=WILLIAMS[group%4];rr=random.Random(seed+group*1103)
        queues={c:[t for t in trials if (t['condition_id'].startswith('hard'))+2*(t['condition_id'].endswith('high'))==c] for c in range(4)}
        for q in queues.values():rr.shuffle(q)
        ordered=[queues[c].pop() for _ in range(6) for c in order]
        # Assistance is a separate mode, randomized before task and explicitly balanced by family.
        for task in ['readability','visual_search','mixed']:
            subset=[t for t in ordered if t['task']==task]
            options=['none','zoom_text','increase_contrast'] if task=='readability' else ['none','highlight_region','highlight_target','zoom_text'] if task=='visual_search' else ['none','zoom_text','increase_contrast','highlight_region']
            options=options[group%len(options):]+options[:group%len(options)]
            assigned=(options*math.ceil(len(subset)/len(options)))[:len(subset)];rr.shuffle(assigned)
            for t,a in zip(subset,assigned):t['assigned_assistance']=a;t['assigned_assistance_semantics']='oracle_target_location' if a=='highlight_target' else 'region_cue_contains_multiple_options' if a=='highlight_region' else a
        plans[str(group)]=ordered
        for i,t in enumerate(ordered):balance.append({'group':group,'order':i,**{k:t[k] for k in ['trial_id','task','target_id','target_text','domain','semantic_group','condition_id','pair_id','matched_condition_id','assigned_assistance']},
            'target_zone':t['target_position']['zone_2x2'],'font_glyph_height':t['conditions']['glyph_height_px'],'element_count':len(t['elements']),'seed':seed})
    fixation=[deepcopy(t) for t in build_protocol(seed,2)['trials'] if t['task']=='fixation']
    return {'schema_version':'temporal-pilot-v3','protocol_version':'mobile-pilot-rsm-v3','seed':seed,'counterbalance_groups':16,
        'plans':plans,'quick_plans':{g:quick_subset(t) for g,t in plans.items()},'trials':fixation+plans['0'],'assistance_actions':ASSIST,'target_vocabulary':vocab,
        'label_policy':'conditions are manipulations, not self-reported difficulty; no-help is not no-difficulty'},balance


def render_example(trial,path,assistance='none'):
    font_path=None;font=load_font(36,font_path)[0];im=Image.new('RGB',(1080,1920),'white');d=ImageDraw.Draw(im)
    d.text((36,90),trial['instruction'],font=font,fill='black')
    for r in trial.get('regions',[]):
        d.rounded_rectangle(r['box'],radius=14,fill=tuple(r['background_rgb']))
        d.text((r['box'][0]+12,r['box'][1]+8),r['label'],font=load_font(24)[0],fill=(70,70,70))
    for e in trial['elements']:
        box=e['bounding_box_px'];bg=tuple(e['background_rgb']);d.rounded_rectangle(box,radius=12,fill=bg,outline='#aaa',width=2)
        d.ellipse((box[0]+8,box[1]+8,box[0]+20,box[1]+20),fill=(80,110,145))
        f=load_font(int(e['font_glyph_height_px']),font_path)[0];lines=e['text_lines'];cx=(box[0]+box[2])/2;cy=(box[1]+box[3])/2
        for j,text in enumerate(lines):
            bounds=d.textbbox((0,0),text,font=f);x=cx-(bounds[2]-bounds[0])/2;y=cy+(j-(len(lines)-1)/2)*(e['font_glyph_height_px']+6)-(bounds[3]-bounds[1])/2-bounds[1]
            d.text((x,y),text,font=f,fill=(35,35,35))
    im.save(path)


def generate_design(output='reports/pilot_v3/design',asset='mobile_pilot/app/src/main/assets/protocol_v3.json',seed=42):
    out=Path(output);out.mkdir(parents=True,exist_ok=True);protocol,balance=build_protocol_v3(seed)
    enriched=[]
    for word in protocol['target_vocabulary']:
        variants=[{k:t[k] for k in ['target_id','target_text','domain','semantic_group','distractor_pool','difficulty_manipulation','target_position','matched_condition_id','pair_id','randomization_block_id','randomization_seed','counterbalance_group','condition_id']} for ts in protocol['plans'].values() for t in ts if t['target_id']==word['target_id']]
        enriched.append({**word,'usage':'session_target' if variants else 'distractor_pool_only',
            'randomization_seed':seed,'distractor_pool':sorted({v for t in variants for v in t['distractor_pool']}),
            'difficulty_manipulation':{'readability':['easy','hard'],'search_load':['low','high'],'human_label':False} if variants else None,
            'target_position':sorted({t['target_position']['zone_2x2'] for t in variants}),
            'matched_condition_id':sorted({t['matched_condition_id'] for t in variants}),
            'pair_id':variants[0]['pair_id'] if variants else None,'variants':variants})
    (out/'target_vocabulary.json').write_text(json.dumps(enriched,ensure_ascii=False,indent=2));csv_write(out/'stimulus_factorial_design.csv',balance)
    Path(asset).write_text(json.dumps(protocol,ensure_ascii=False,indent=2))
    # machine-readable checks across all participants, targets, cells and positions
    summary={'groups':16,'trials_per_session':24,'unique_targets_per_session':{},'cell_counts':{},'zone_counts':{},'cell_zone_tables':{},'target_exposure_check':True}
    for group,trials in protocol['plans'].items():
        texts=[t['target_text'] for t in trials];summary['unique_targets_per_session'][group]=len(set(texts));summary['cell_counts'][group]=dict(Counter(t['condition_id'] for t in trials));summary['zone_counts'][group]=dict(Counter(t['target_position']['zone_2x2'] for t in trials));assert set(summary['zone_counts'][group].values())=={6}
        summary['cell_zone_tables'][group]=dict(Counter(t['condition_id']+'_'+str(t['target_position']['zone_2x2']) for t in trials))
        for t in trials:
            assert all(e['text'] not in set(texts)-{t['target_text']} for e in t['elements'])
    summary['quick_cell_counts']={g:dict(Counter(t['condition_id'] for t in ts)) for g,ts in protocol['quick_plans'].items()}
    summary['quick_zone_counts']={g:dict(Counter(t['target_position']['zone_2x2'] for t in ts)) for g,ts in protocol['quick_plans'].items()}
    summary['assistance_counts']={g:dict(Counter(t['task']+'_'+t['assigned_assistance'] for t in ts)) for g,ts in protocol['plans'].items()}
    (out/'balance.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    for task in ['readability','visual_search','mixed']:
        t=next(t for t in protocol['plans']['0'] if t['task']==task);render_example(t,out/(task+'_example.png'))
    (out/'task_taxonomy.md').write_text('''# R/S/M protocol v3

R=low search load（6选项），分easy/hard字形；S=high load（24选项）+easy字形；M=high load+hard字形。M是操控条件，不是困难真值。基础2×2只操控glyph height（32/20参考像素）及choice count（6/24），font weight=400、四块背景、潜在slot位置保持一致；语义相似度由同任务族词库配平并记录，本轮不同时随机改变8个因素。实际Android字形高度、背景及对比度仍需真机导出核对，PIL预览不是Android截图。

每Session24个不同target，所有其他Session target均从该Session distractors排除，避免提前暴露后续答案。允许重复干扰项，因此仍可能有界面熟悉化；按trial order分析。跨16个group轮换target的4个condition与4个zone，使用Williams四序列平衡条件顺序。pair_id是语义/任务族匹配，不表示重复同一图片或相同词。需要更多人后检查实际反应与自评，不预先宣称hard一定困难。

Assistance是独立研究模式：requested_only保留无预帮助、记录用户选择；assigned_pre_task在trial开始前随机分配，并单独报告。若随机条件下主动求助，标rescue_crossover，不混入原分配的纯比较。highlight_target=oracle正确位置强帮助；highlight_region=包含多选项的区域提示；二者不得等价比较。个人偏好、自评困难、实际有帮助三类字段分开。

R优先比较none/zoom_text/increase_contrast；S比较none/highlight_region/highlight_target/zoom_text；M先允许用户选择或随机单项，组合帮助作为明确的多次intervention序列记录，不能并成一个无定义标签。不要从单人的帮助前后速度推断因果收益。
''')
    (out/'condition_balance_report.md').write_text('# Condition balance\n\n16组，每组24个独立目标；每cell6项，每zone6项；各cell×zone计数为1或2。每个target跨16组覆盖4条件×4区域。全Session目标保留为reserved，不出现在其他页干扰项。seed='+str(seed)+'。\n\n'+json.dumps(summary,ensure_ascii=False,indent=2)+'\n\n初始2×2将contrast/weight固定并逐元素记录；要比较它们应另建单因素子研究，而不是同时改变全部因素。辅助随机化与cell×zone不完全正交，小样本必须报告实际交叉表，不得宣称完美平衡。\n')
    return summary

if __name__=='__main__':print(json.dumps(generate_design(),ensure_ascii=False))
