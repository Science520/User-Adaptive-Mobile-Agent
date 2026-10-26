"""Balanced, reproducible *interactive task specifications*, never difficulty labels."""
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from scipy.linalg import hadamard
from PIL import Image, ImageDraw
from .synthetic import load_font
from .geometry import contrast_ratio
from .io import write_json, sha256

VOCABULARY={
 'medical':'门诊预约 预约记录 检验报告 检查预约 住院服务 我的处方 家庭医生 健康档案 在线问诊 用药咨询 体检预约 体检报告 就诊人管理 电子健康卡 医疗缴费 候诊查询 就诊指南 疫苗接种 医保结算 慢病管理 复诊预约 出院小结 费用明细 发票申请'.split(),
 'transport':'公交查询 地铁线路 乘车记录 实时公交 车票预订 火车时刻 出租车服务 机场巴士 城际客运 长途汽车 我的车票 退票申请 改签服务 站点查询 停车缴费 交通卡充值 骑行服务 线路收藏 到站提醒 出行计划 通勤路线 无障碍出行 失物招领 客服咨询'.split(),
 'utilities':'电费缴纳 水费缴纳 燃气缴费 暖气缴费 宽带续费 手机充值 账单查询 缴费记录 住址管理 物业服务 报修申请 小区公告 快递查询 社区服务 垃圾分类 家政预约 充电服务 费用明细 自动缴费 用量查询 发票申请 户号管理 余额查询 服务网点'.split(),
 'shopping':'我的订单 购物车 待付款 待发货 待收货 退款售后 收货地址 优惠券 商品收藏 浏览记录 物流查询 发票管理 联系客服 评价管理 常购清单 会员中心 积分兑换 领券中心 附近门店 到店自提 价格保护 退货进度 商品分类 购物清单'.split(),
 'qr':'乘车码 付款码 收款码 会员码 停车缴费 快递取件 门禁通行 共享单车 设备配网 商品溯源 电子票券 身份核验 预约核销 优惠券 扫一扫 扫码点餐 扫码打印 场馆入场 充电服务 扫码报修 包裹寄件 交通卡 服务签到 码上服务'.split()}
FACTORS=['glyph','button','count','eccentricity','contrast','semantic_similarity','information_density','target_side']


def template_hash(trial):
    keys=['task','target_element_id','elements','conditions','instruction']
    return hashlib.sha256(json.dumps({k:trial[k] for k in keys},ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def validate_trial(trial):
    w,h=trial['base_size_px'];elements=trial['elements'];ids=[e['element_id'] for e in elements]
    if len(set(ids))!=len(ids):raise ValueError('Duplicate element ID')
    if sum(e['role']=='target' for e in elements)!=1:raise ValueError('Exactly one instructed target required')
    if trial['target_element_id'] not in ids:raise ValueError('Missing target')
    for e in elements:
        for key in ['bounding_box_px','clickable_region_px']:
            x0,y0,x1,y1=e[key]
            if not (0<=x0<x1<=w and 0<=y0<y1<=h):raise ValueError('Element outside screen')
        x0,y0,x1,y1=e['bounding_box_px'];a,b,c,d=e['clickable_region_px']
        if not(a<=x0 and b<=y0 and c>=x1 and d>=y1):raise ValueError('Visual target exceeds click area')
    for i,a in enumerate(elements):
        for b in elements[i+1:]:
            x0,y0,x1,y1=a['clickable_region_px'];a0,b0,a1,b1=b['clickable_region_px']
            if min(x1,a1)>max(x0,a0) and min(y1,b1)>max(y0,b0):raise ValueError('Ambiguous overlapping click areas')
    return True


def build_protocol(seed=42,repetitions=2):
    if repetitions not in (2,3):raise ValueError('Fixation repetitions must be 2 or3')
    rng=np.random.default_rng(seed);trials=[]
    for rep in range(repetitions):
        for idx in rng.permutation(25):
            x=1080*(.1+.2*(int(idx)%5));y=1920*(.12+.19*(int(idx)//5))
            element={'element_id':'fixation','text':'●','text_lines':['●'],'bounding_box_px':[x-12,y-12,x+12,y+12],
                'clickable_region_px':[x-24,y-24,x+24,y+24],'font_glyph_height_px':24,'role':'target',
                'foreground_gray':0,'visual_contrast':21.,'page_id':'fixation','navigation_transition':None}
            t={'trial_id':f'A_r{rep:02d}_p{idx:02d}','task':'fixation','page_id':'fixation','base_size_px':[1080,1920],
               'instruction':'请自然注视圆点','target_element_id':'fixation','target_position_px':[x,y],
               'fixation_duration_ms':1500,'timeout_ms':1500,'correct_action_path':[],
               'conditions':{'grid':[5,5],'repeat':rep,'label_kind':'instructed_target_not_eye_tracker_truth'},'elements':[element]}
            t['template_id']=template_hash(t);validate_trial(t);trials.append(t)
    # 3 x 16-run orthogonal main-effect design: each factor/pair balanced. Higher-order interactions are aliased.
    design=np.tile((hadamard(16)[:,1:9]>0).astype(int),(3,1));design=design[rng.permutation(48)]
    domains=list(VOCABULARY)
    for i,bits in enumerate(design):
        factor=dict(zip(FACTORS,map(int,bits)));domain=domains[i%len(domains)]
        count=[12,24][factor['count']];glyph=[22,28][factor['glyph']];bw,bh=[(220,80),(244,128)][factor['button']]
        gray=[35,145][factor['contrast']];area_h=[1300,1060][factor['information_density']]
        pool=VOCABULARY[domain] if factor['semantic_similarity'] else list(dict.fromkeys(t for v in VOCABULARY.values() for t in v))
        texts=rng.choice(pool,count,replace=False).tolist();cols=4;nrows=math.ceil(count/cols)
        centers=[(36+(j%cols+.5)*252,340+(j//cols+.5)*area_h/nrows) for j in range(count)]
        side=[j for j,(x,y) in enumerate(centers) if (x>=540)==bool(factor['target_side'])]
        distance=np.array([np.linalg.norm((np.array(centers[j])-[540,960])/[1080,1920]) for j in side])
        target=side[int(distance.argmax() if factor['eccentricity'] else distance.argmin())]
        elements=[]
        for j,(text,(x,y)) in enumerate(zip(texts,centers)):
            box=[x-bw/2,y-bh/2,x+bw/2,y+bh/2]
            elements.append({'element_id':f'service_{j:02d}','text':text,'text_lines':[text]+(['便民服务'] if factor['information_density'] else []),
                'bounding_box_px':box,'clickable_region_px':box,'font_glyph_height_px':glyph,
                'role':'target' if j==target else 'distractor','foreground_gray':gray,'visual_contrast':contrast_ratio(gray),
                'page_id':domain,'navigation_transition':'task_complete' if j==target else None})
        t={'trial_id':f'B_{i:03d}','task':'visual_search','page_id':domain,'base_size_px':[1080,1920],
           'instruction':'请找到并点击「'+texts[target]+'」','target_element_id':elements[target]['element_id'],
           'timeout_ms':30000,'correct_action_path':[elements[target]['element_id']],
           'conditions':{'factor_levels':factor,'domain':domain,'glyph_height_px':glyph,'button_size_px':[bw,bh],
                         'element_count':count,'target_eccentricity_normalized':float(np.linalg.norm((np.array(centers[target])-[540,960])/[1080,1920])),
                         'contrast_ratio':contrast_ratio(gray),'semantic_similarity':factor['semantic_similarity'],
                         'information_density':factor['information_density'],'target_location_px':list(centers[target])},'elements':elements}
        t['template_id']=template_hash(t);validate_trial(t);trials.append(t)
    return {'schema_version':'pilot-stimuli-v1','seed':seed,'fixation_repetitions':repetitions,'trials':trials,
        'design':'48 trials = three16-run Hadamard blocks,8 pairwise-balanced binary main effects; higher-order interactions not independently identified',
        'factor_names':FACTORS,'condition_is_human_difficulty':False,'fixation_truth':'instructed target only'}


def render_trial(trial,path,font_path=None):
    """Reference reconstruction; Android records its exact on-device PNG + measured glyph metadata."""
    validate_trial(trial);im=Image.new('RGB',tuple(trial['base_size_px']),'white');draw=ImageDraw.Draw(im)
    header,_=load_font(40,font_path);draw.text((36,80),trial['instruction'],font=header,fill='black')
    metadata=[]
    for e in trial['elements']:
        box=e['bounding_box_px'];cx=(box[0]+box[2])/2;cy=(box[1]+box[3])/2
        if trial['task']=='fixation':draw.ellipse(box,fill='black');metadata.append(e);continue
        draw.rounded_rectangle(box,radius=10,outline='#bbbbbb',width=2)
        desired=e['font_glyph_height_px'];font,actual_font=load_font(desired,font_path)
        for _ in range(3):
            b=font.getbbox(e['text']);actual=b[3]-b[1];font,actual_font=load_font(max(1,round(font.size*desired/max(actual,1))),font_path)
        b=font.getbbox(e['text']);glyph=b[3]-b[1];lines=e['text_lines'];ink=[]
        for j,text in enumerate(lines):
            pos=(cx,cy+(j-(len(lines)-1)/2)*(desired+5));bb=draw.textbbox(pos,text,font=font,anchor='mm')
            if bb[0]<box[0] or bb[2]>box[2] or bb[1]<box[1] or bb[3]>box[3]:raise ValueError('Text ink overflows controlled button')
            draw.text(pos,text,font=font,anchor='mm',fill=(e['foreground_gray'],)*3);ink.append(list(bb))
        metadata.append({**e,'actual_glyph_height_px':glyph,'ink_bounding_boxes_px':ink,'font_path':actual_font})
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);im.save(path)
    write_json(path.with_suffix('.json'),{'trial':trial,'rendered_elements':metadata,'reconstruction_kind':'reference_font_not_android_pixel_identical',
              'image_sha256':sha256(path),'render_timestamp_ns':None})
    return str(path)


def build_stimuli(output='mobile_pilot/stimuli',seed=42,repetitions=2,previews=6,mock_output=None):
    output=Path(output);protocol=build_protocol(seed,repetitions);write_json(output/'protocol.json',protocol)
    write_json(output/'vocabulary.json',VOCABULARY)
    design=[t['conditions']['factor_levels'] for t in protocol['trials'] if t['task']=='visual_search']
    matrix=np.array([[d[k] for k in FACTORS] for d in design]);correlation=np.corrcoef(matrix.T)
    write_json(output/'design_audit.json',{'trials':len(design),'ones_per_factor':matrix.sum(0).tolist(),
        'pairwise_correlation':correlation.tolist(),'labels':'experimental conditions only, not difficulty truth','seed':seed})
    selected=[protocol['trials'][0]]+[t for t in protocol['trials'] if t['task']=='visual_search'][:max(0,previews-1)]
    for t in selected:render_trial(t,output/'previews'/f"{t['trial_id']}.png")
    # Android uses this same specification; the view scales and records actual pixel coordinates.
    asset=Path('mobile_pilot/app/src/main/assets/protocol.json');write_json(asset,protocol)
    result={'protocol':str(output/'protocol.json'),'trials':len(protocol['trials']),'search_trials':len(design),'pairwise_max_abs_offdiag':float(abs(correlation-np.eye(8)).max())}
    if mock_output:
        from .pilot_session import make_mock_sessions
        result['mock_sessions']=make_mock_sessions(mock_output)
    return result


def export_recorded_ui(session,output,allow_mock=False):
    """Export exact app-rendered PNG + measured metadata, not a differently rasterized approximation."""
    import shutil
    from .pilot_session import session_folder,verify_folder,read_trial,safe_path
    output=Path(output);files=[]
    with session_folder(session) as root:
        verified=verify_folder(root,allow_mock)
        for entry in verified['trials']:
            t=read_trial(root/'trials'/entry['trial_id']);state=t['ui'][0]
            source=safe_path(root/'trials'/entry['trial_id'],state['screenshot_path'])
            dest=output/verified['session_id']/(entry['trial_id']+'.png');dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,dest)
            write_json(dest.with_suffix('.json'),{'ui_state':state,'stimulus':t['meta']['stimulus'],
                'screenshot_sha256':sha256(dest),'provenance':'exact saved mock fixture snapshot' if verified['evidence_tier']=='mock' else 'exact saved app drawing snapshot; not physical compositor screenshot',
                'evidence_tier':verified['evidence_tier']})
            files.append(str(dest))
    return {'exported_stimuli':len(files),'files':files}
