"""Standalone, local-only scientific event timeline; no face pixels or remote resources."""
import html,json
from pathlib import Path

def render_timeline(trials,trial_data,mapped,assistance,path):
    rows=[];colors={'Camera':'#277c4c','UI':'#315b9c','Touch':'#666','Help':'#c22','Assistance':'#c47714','Feedback':'#793995'}
    for row in trials:
        d=trial_data[row['trial_id']];start=row['onset_ns'];feedback=d['feedback'];end=max(row['offset_ns'],feedback.get('timestamp_ns',row['offset_ns']));duration=(end-start)/1e9+.15
        channels={'Camera':[('frame',int(t)) for t in mapped if start<=t<=row['offset_ns']],
                  'UI':[(f'UI v{s.get("ui_state_version",0)}',s['timestamp_ns']) for s in d['ui']],
                  'Touch':[(t['action'],t['timestamp_ns']) for t in d['touch'] if t['action']!='help_request'],
                  'Help':[('help_request',t['timestamp_ns']) for t in d['touch'] if t['action']=='help_request'],
                  'Assistance':[(a['type']+':'+str(a.get('delivered_action')),a['timestamp_ns']) for a in assistance if a['trial_id']==row['trial_id']],
                  'Feedback':[('self-report',feedback['timestamp_ns'])] if feedback.get('timestamp_ns') else []}
        tracks=[]
        for name,events in channels.items():
            marks=''.join(f'<i tabindex="0" title="{html.escape(label)} at {(t-start)/1e9:.3f}s" style="left:{100*(t-start)/1e9/duration:.4f}%;background:{colors[name]}"></i>' for label,t in events)
            tracks.append(f'<label>{name}</label><div class="lane">{marks}</div>')
        rows.append(f'<section data-family="{html.escape(row["task"])}"><h3>{html.escape(row["trial_id"])} · {html.escape(row["target_text"])} · rating {row["difficulty_rating"]}</h3><p>Task {row["duration_s"]:.3f}s; axis includes feedback up to {duration:.2f}s</p><div class="tracks">'+''.join(tracks)+'</div></section>')
    result='''<!doctype html><meta charset="utf-8"><title>Actual Session timeline</title><style>body{font:14px system-ui;margin:28px;max-width:1500px}section{margin:30px 0;padding:16px;background:#fafafa;border:1px solid #ddd}.tracks{display:grid;grid-template-columns:85px 1fr;gap:5px}.lane{height:18px;background:#e9edf1;position:relative}i{position:absolute;top:0;width:3px;height:18px}i:hover,i:focus{outline:2px solid black;z-index:5}h3{margin:4px 0}label{font-size:12px}</style><h1>真实Session时序 · encoded PTS映射 UNVERIFIED</h1><p>Camera为解码视频的估计时刻，其他轨道为原始elapsed事件；悬停查看相对时间。不得将图上的贴合或最近帧残差叫物理同步误差。没有面部图片、没有网络请求。</p>'''+''.join(rows)
    Path(path).write_text(result)
    return {'trials':len(rows),'channels':list(colors),'physical_sync_status':'unverified'}
