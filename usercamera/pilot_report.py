"""Quality-first pilot report: implementation/fixture evidence is not user evidence."""
import json
import os
import shutil
import platform
from pathlib import Path
from .io import read_jsonl,write_json,sha256


def plot_quality(output,extractions,quality):
    from .visualize_mpii import pyplot
    from .pilot_session import session_folder,read_trial,map_camera_frame
    import numpy as np
    plt=pyplot();figures=output/'figures';figures.mkdir(parents=True,exist_ok=True)
    if extractions:
        source=Path(extractions[0]['input_source'])
        if source.exists():
            with session_folder(source) as root:
                s=json.loads((root/'session.json').read_text())
                trial_id=next((i for i in s['trial_ids'] if read_trial(root/'trials'/i)['meta']['task']=='visual_search'),None)
                if trial_id:
                    t=read_trial(root/'trials'/trial_id);start=t['meta']['onset_ns'];fig,ax=plt.subplots(figsize=(11,4),constrained_layout=True)
                    captures=[map_camera_frame(r,True)[0] for r in t['camera'] if r['status']=='recorded']
                    captures=[(v-start)/1e9 for v in captures if v is not None]
                    ax.scatter(captures,[2]*len(captures),s=12,label='saved camera capture (mapped)')
                    arrivals=[(r['arrival_elapsed_ns']-start)/1e9 for r in t['camera'] if r['status']=='recorded']
                    ax.scatter(arrivals,[1.7]*len(arrivals),s=10,marker='x',label='arrival / availability lower bound')
                    ui=[(r['timestamp_ns']-start)/1e9 for r in t['ui']];touch=[(r['timestamp_ns']-start)/1e9 for r in t['touch']]
                    ax.scatter(ui,[1]*len(ui),label='UI draw submission');ax.scatter(touch,[.5]*len(touch),label='touch events')
                    if 'timestamp_ns' in t['feedback']:ax.scatter([(t['feedback']['timestamp_ns']-start)/1e9],[0],c='red',label='post-trial feedback: label only')
                    for v in [1,2,3]:ax.axvline(v,color='gray',alpha=.5,ls='--');ax.text(v,2.4,f'{v}s prefix',fontsize=8)
                    ax.axvline((t['meta']['offset_ns']-start)/1e9,c='black',label='trial offset')
                    ax.set_yticks([0,.5,1,1.7,2],['feedback','touch','UI','arrival','capture']);ax.set_xlabel('seconds from recorded onset');ax.set_ylim(-.2,2.6)
                    ax.set_title(s['evidence_tier'].upper()+': timestamp replay, not physical synchronization proof');ax.legend(fontsize=7,loc='upper right')
                    fig.savefig(figures/'timeline.png',dpi=150);plt.close(fig)
    if quality:
        fig,axes=plt.subplots(1,2,figsize=(12,4),constrained_layout=True)
        for index,q in enumerate(quality):
            fps=[t['actual_saved_fps'] for t in q['trials'] if t['actual_saved_fps'] is not None]
            axes[0].bar(index,float(np.mean(fps)) if fps else 0)
            axes[1].bar(index,q['missing_camera_trial_fraction'] or 0)
        for ax in axes:ax.set_xticks(range(len(quality)),[q['session_id'] for q in quality],rotation=25)
        axes[0].set_ylabel('Mean saved FPS (not sensor FPS)');axes[1].set_ylabel('Camera-missing trial fraction');axes[1].set_ylim(0,1)
        fig.savefig(figures/'recording_quality.png',dpi=150);plt.close(fig)
    return str(figures)


def build_environment():
    sdk=Path(os.environ.get('ANDROID_SDK_ROOT',os.environ.get('ANDROID_HOME',str(Path.home()/'Library/Android/sdk'))))
    # macOS /usr/bin/java can be a stub; do not count it as an installed JDK.
    jdk=bool(os.environ.get('JAVA_HOME') and (Path(os.environ['JAVA_HOME'])/'bin/java').exists())
    return {'sdk_path':str(sdk),'android_sdk_found':(sdk/'platforms/android-35/android.jar').exists(),
        'gradle_executable':shutil.which('gradle'),'java_home_configured':jdk,'wrapper_present':Path('mobile_pilot/gradle/wrapper/gradle-wrapper.jar').is_file(),
        'apk_compiled':False,'device_capture_tested':False,'build_status':'not_compiled_in_this_environment; no SDK35 or usable JDK detected during task',
        'python':platform.python_version()}


def generate_pilot_report(output='reports/pilot',expansion_output='reports/mpii_expansion'):
    output,expansion_output=Path(output),Path(expansion_output);output.mkdir(exist_ok=True,parents=True)
    environment=build_environment();write_json(output/'build_environment.json',environment)
    environment['build_attempt_log']='android_build_attempt.log' if (output/'android_build_attempt.log').exists() else None
    write_json(output/'build_environment.json',environment)
    quality=[json.loads(p.read_text()) for p in sorted((output/'quality').glob('*.json'))]
    extracted=[json.loads(p.read_text()) for p in sorted((output/'features').rglob('extraction.json'))]
    result_path=output/'temporal_results.json';result=json.loads(result_path.read_text()) if result_path.exists() else None
    integration_path=expansion_output/'integration.json';integration=json.loads(integration_path.read_text()) if integration_path.exists() else None
    expansion_path=expansion_output/'expanded_results.json';expanded=json.loads(expansion_path.read_text()) if expansion_path.exists() else None
    real=[q for q in quality if q['evidence_tier']!='mock'];mock=[q for q in quality if q['evidence_tier']=='mock']
    plot_quality(output,extracted,quality)
    lines=['# Phase2 Temporal User–Screen Mobile Pilot','',
        '已实现可构建的Android工程、可重建交互刺激、Session导出格式、离线提取器、质量检查和时序基线。**本机没有Android SDK/JDK，APK未编译，尚未真机采集；mock指标只是软件管道测试。**','',
        '## 本机实际完成','',
        f"校验Session：real={len(real)}, mock={len(mock)}；提取日志={len(extracted)}。Mock图片为程序生成图案，没有人脸视频或真实参与者。",'',
        'Android源码：Compose负责控制/自评界面，Canvas负责可点击刺激和真实像素布局；CameraX仅用ImageAnalysis记录带传感器时间戳的JPEG序列，不使用MediaProjection、VideoCapture或第三方上传（Manifest无INTERNET权限）。Task A默认25点×2轮，可选3轮；Task B48个trial，8个二水平主效应两两平衡，但高阶交互有混杂，域/词汇不是独立全因子设计。','',
        '## MPII扩展','']
    if integration:
        lines+=[f"原始{integration['n_original']} + 新增{integration['n_expansion']} = {integration['n_total']}。新增hash/解码通过：{integration['new_file_hashes_and_decode_verified']}。新增视图：{integration['expansion_membership']}；合并视图：{integration['combined_membership']}。本次数据集下载0。",'',
            '旧data/processed、manifest、splits及历史报告均保留；新视图data/views/mpii_v2_720。15折以原验证/测试IDs固定，仅训练312→624；新增360测试单独汇报，不能混作模型提升。']
    if expanded:
        lines+=['','| 模型 | 原360固定测试角度mean° | 原360屏幕误差mm |','|---|---:|---:|']
        for name,v in expanded['primary_original360'].items():
            m=v['metrics'];lines.append(f"| {name} | {m['angular_error_deg']['mean']:.3f} | {m['screen_direct_error_mm']['mean']:.2f} |")
        lines+=['',f"部分微调完成：{expanded['neural_completed']}；估计/实际每折配置与运行日志见 ../mpii_expansion。旧微调控制组仅在源码、split IDs及12epoch配置完全一致时复用；因旧版没有保存模型checkpoint，其新增360测试预测明确未计算。",'',
            'MPII仍是静态笔记本图片；本次扩展不提供手机连续流或真实困难证据。']
        cost=expansion_output/'training_cost.json'
        if cost.exists():
            cost_data=json.loads(cost.read_text());lines+=['',f"扩展部分微调实际完成{cost_data['completed_folds']}折、{cost_data['candidate_fits']}个候选fit，CPU执行耗时计时总和约{cost_data['actual_fit_elapsed_minutes_sum_on_cpu']:.1f}分钟；不含最初embedding/stem提取，不是CPU core-seconds。Expanded Original视图保留3条越界新标签，数据量效应尚未独立剥离异常样本/采集日构成变化。"]
    lines+=['','## 时间与质量判定','',
        '所有UI/trial/feedback用elapsedRealtimeNanos。Touch eventTime来自uptimeMillis，逐事件夹取两个elapsed读数并保存偏移及量化不确定性。Camera REALTIME直接使用capture sensor timestamp；UNKNOWN预热偏移仅为arrival-sensor下包络估计，不能消除最小流水线延迟，其真实同步误差为未知。默认不把UNKNOWN估计伪装成已同步数据；独立capture-clock anchor映射才能验证。',
        'draw callback时间是绘制提交代理，不能当作物理屏幕发光时间。保存原始sensor、arrival、stored和映射时间；固定prefix只使用capture及可用时间都在cutoff前的帧。编码视频PTS没有被用作系统时钟。',
        '质量报告包含实际保存FPS、采样略过/写失败、帧间隔推定缺口、clock状态、模态缺失。CameraX KEEP_ONLY_LATEST的真实driver丢帧数量不可直接观测，推定缺口不宣称精确丢帧；capture到arrival延迟也不是同步误差。暂停中止当前trial，恢复新attempt，不拼接成伪连续流。','',
        '| Session | evidence | trials | 缺camera比例 | clock usable |','|---|---|---:|---:|---|']
    for q in quality:lines.append(f"| {q['session_id']} | {q['evidence_tier']} | {len(q['trials'])} | {q['missing_camera_trial_fraction']:.3f} | {q['clock_alignment_usable']} |")
    lines+=['','![时间线回放（不证明物理同步）](figures/timeline.png)','', '![记录质量](figures/recording_quality.png)']
    lines+=['','## 离线特征与标签边界','',
        'MediaPipe FaceLandmarker输出head y/p/r、相对位置、face scale和图像质量。单目距离仅为inverse-face-scale proxy；无独立量具标定不输出绝对mm。FaceLandmarker没有返回可用的检测概率/眼点visibility，字段保持null；可另供FaceDetector模型获得检测分数，眼点是否在图像内仅为单独proxy。没有可靠屏幕gaze映射时gaze region为空，不把iris或head yaw充当gaze。',
        '时序量只来自同一真实trial的原始时间戳：相对scale变化、旋转角/角速度、姿态波动、可用时gaze占比、触摸暂停/错误/距上次操作时间。没有将MPII静态图片排序为视频。',
        '反馈保留原始1–5分、困难类型、帮助意愿、干预偏好；outcome和UI条件独立保存。基线预先定义rating>=3为二分类，trial-level自评不复制为逐帧困难起点。偏好不是干预效果真值，H3未验证。','',
        '## 时序基线实际执行','',
        'M0 S；M1 S+A；M2 U；M3 S+U；M4 S+A+U；M5 S+A+前一trial的错位U。错位供体只在当前训练/验证/测试partition内、同人同Session的过去trial中选择；首trial缺失，不能把它解释为严格匹配缺失率的因果对照。',
        '分别评估trial结束时和固定1/2/3秒prefix；未持续到prefix的trial明确排除并记录，可能造成只评价较慢trial的选择偏差。Logistic与HGB用内部验证Brier选择；小型GRU hidden16、6个因果累计时间点、验证early stopping。imputer/scaler只拟合训练组。单人按Session分组，多人才按参与者分组；额外purge跨partition重复UI模板。',
        '输出AUROC、Macro-F1、balanced accuracy、Brier/ECE校准、逐组指标、输入缺失和split IDs。数据不足三组则明确insufficient；不为凑指标进行随机trial划分。']
    if result:
        lines+=['',f"实际运行数据层：**{result['evidence_tier']}**；算法：{result['algorithms']}。以下状态仅确认代码运行，不能证明Camera对真实困难有增益。",'',
            '| Mode | N | Split status | Model variants |','|---|---:|---|---:|']
        for mode,v in result['evaluation_modes'].items():lines.append(f"| {mode} | {v['n']} | {v['scope']['status']} | {len(v['models'])} |")
    lines+=['','## 需要真实设备 / 真实数据才能完成','',
        'Android编译、权限拒绝/前摄缺失、生命周期中断、JPEG颜色与旋转、各机型实际FPS、屏幕物理坐标、布局溢出、ZIP导出和删除必须在真机逐项确认。APK构建尚未执行；当前不声称原型已在手机运行。提供原生JUnit源码，但本机仅执行Python单元/集成测试。',
        'H1：手机gaze/pose/distance可靠性仍需独立参考；fixation是instructed target而非独立测得gaze truth。H2：需真实同步Session与主动自评，mock分数不是证据。H3：没有实施或验证任何界面干预。C/D可选任务未实现，以先验证A/B采集可靠性。无GUI Agent、GRPO、大模型或招募。','',
        '## 运行入口','',
        '完整命令、构建与采集步骤见 ../../mobile_pilot/README.md；格式见 ../../mobile_pilot/SCHEMA.md；协议见 ../../mobile_pilot/PILOT_PROTOCOL.md。',
        '```bash','cd /Users/audrey/Desktop/Phone',
        '.venv/bin/python -m usercamera mpii-integrate-expansion',
        '.venv/bin/python -m usercamera mpii-eval-expanded',
        '# 先查看neural_resource_estimate.json；下面才启用完整部分微调',
        '.venv/bin/python -m usercamera mpii-eval-expanded --run-neural --max-epochs 12',
        '.venv/bin/python -m usercamera pilot-build-stimuli',
        '# mock_sessions已提供，重复生成需指定新的--mock-output目录',
        '.venv/bin/python -m usercamera pilot-verify-session mobile_pilot/mock_sessions/mock_s00 --allow-mock',
        '.venv/bin/python -m usercamera pilot-extract-features mobile_pilot/mock_sessions --backend mock --allow-mock',
        '.venv/bin/python -m usercamera pilot-evaluate --allow-mock',
        '.venv/bin/python -m usercamera pilot-report',
        'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q','```','',
        '参考：[Camera2 timestamp source](https://developer.android.com/reference/android/hardware/camera2/CameraMetadata)、[CameraX ImageAnalysis](https://developer.android.com/media/camera/camerax/analyze)、[MediaPipe FaceLandmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python)、[AGP8.7构建要求](https://developer.android.com/build/releases/agp-8-7-0-release-notes)。']
    (output/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    verification=output/'verification.json'
    if verification.exists():
        v=json.loads(verification.read_text())
        with (output/'RESULTS.md').open('a') as f:f.write(f"\n保存校验：旧报告/processed文件{v['historical_files_verified']}个哈希未变；原始{v['raw_files_verified']}个文件和扩展{v['expansion_files_verified']}个文件哈希通过。测试：`{v['pytest_output'].strip().splitlines()[-1]}`。\n")
    write_json(output/'run_manifest.json',{'build_environment':environment,'real_sessions_verified':len(real),'mock_sessions_verified':len(mock),
        'supports_real_H2':False,'supports_H3':False,'code_sha256':{p.name:sha256(p) for p in sorted(Path(__file__).parent.glob('*.py'))},
        'android_source_sha256':{str(p):sha256(p) for p in sorted(Path('mobile_pilot/app/src').rglob('*')) if p.is_file() and p.suffix in ['.kt','.xml']},
        'protocol_sha256':sha256('mobile_pilot/stimuli/protocol.json') if Path('mobile_pilot/stimuli/protocol.json').exists() else None,
        'schema_sha256':sha256('mobile_pilot/schema/session.schema.json') if Path('mobile_pilot/schema/session.schema.json').exists() else None})
    return {'report':str(output/'RESULTS.md'),'apk_compiled':False,'real_sessions_verified':len(real),'mock_sessions_verified':len(mock)}
