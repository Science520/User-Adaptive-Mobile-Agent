# Mobile Pilot v2：Video-First

沿用现有 App / SessionStore，旧 JPEG Session 原样保留。v2 的主记录为一段连续前摄 MP4，覆盖说明、Task A/B、休息及反馈页；Pause/Resume 从视频流中排除暂停时段，并记录 Recorder 事件，当前未完成 trial 仍按旧约定标为 aborted，以新 attempt 重做。摄像头始终不录音，无 INTERNET 权限、无上传入口。前摄预览仅在质量检查页显示，Fixation 为白底单黑点。

默认请求 HD、24–30 FPS，具体编码、尺寸、方向、帧率以真机 Finalize 后 MediaExtractor 检查及电脑 PyAV 解码为准。目标帧率不是保证。若 VideoCapture+ImageAnalysis 绑定失败，则回退 video-only，live features unavailable；JPEG 兼容模式仍可显式选择。ImageAnalysis 是独立 KEEP_ONLY_LATEST 消费者，不进行同步 JPEG 写盘。MediaPipe LIVE_STREAM 在推理忙时舍弃分析输入，不阻塞硬件视频编码；分析丢弃不等于视频硬件丢帧。

实时特征包含 face_count/presence、in-frame eyes proxy、脸尺度/位置、canonical-face pose proxy、blink blendshapes、亮度和推理延迟。FaceLandmarker 不提供可靠逐次检测置信度和逐眼可见度，这些字段为 null；阈值不是置信度。脸尺度不是绝对毫米距离。包内复用已有本地 `data/models/face_landmarker.task`；模型来源及 SHA256 见本轮结果，未重新下载数据。CPU 推理，不需要 Google Play Services。

## 时间关系

- UI：elapsedRealtimeNanos，首个 draw 提交不是 photon onset；真实 View 截图保存实际布局与版本。
- Touch：MotionEvent uptime，通过同时采集 elapsed/uptime 的中点差映射；记录时间采样区间及毫秒量化不确定度。
- Camera analysis：原始 sensor timestamp；REALTIME 与 elapsed 共基准，UNKNOWN 只作未验证估计。它与编码帧不是一一对应，不能当成 PTS 锚点。
- Video：MP4 的逐帧 PTS 由 MediaExtractor 提取；Recorder Start/Resume callback 的到达 elapsed + recordedDuration 构造分段估计，Pause 不能用单个全程偏移量处理。
- 当前没有独立的 sensor↔encoded PTS 配对，或视觉 LED/高速相机同步实验。因此 PTS→elapsed 始终 `unverified`，物理同步 uncertainty 为 null。回放最近帧时间差仅验证估计覆盖，不能解释为测得的物理误差。
- Recorder Finalize 成功后才检查哈希和帧信息；`video_pending` 未清除时禁止导出。进程被强杀、存储失败或未 Finalize 均不得宣称完整。保留失败原文件，不自动修复标注。

## Task / Assistance

Quick Test 为5点×1轮 + 9项搜索，Full 为可选5/9/25点×1/2/3轮 + 36项搜索；每9项搜索后休息，允许跳过/退出。注视点是 instructed target，不是独立眼动真值。真实朝向/镜像和任务充分有效脸帧数仍需要检查，缺失不能插值成观察。

搜索用4组匹配内容，每组 font/position/contrast 两条件及 assistance 三条件。每个 pair 内仅改变指定因素，记录 pair_id/condition_id/randomization_seed，打乱呈现顺序。重复目标存在学习/记忆/顺序效应；需要跨参与者平衡顺序和预注册分析，不能从单任务耗时推断单因素原因。

帮助菜单实际实施 highlight、zoom、contrast、enlarge_touch、explain、none，保存 intervention_onset/end、requested/delivered action 和前后 UI 截图版本。此处 explain 为本受控任务目标提供预先编写的服务含义说明，不是通用语义助手。Zoom 保留按钮位置，扩大字形；触摸扩大会改变 hit regions，优先匹配目标前已有元素顺序，未来需检查边界重叠。帮助反馈含1–5 helpfulness（0=未获得帮助）。事后偏好只是自评。

独立 Preference Adaptation 模式在下一任务开始前，以过去已知偏好随机分配 no_help / preferred / other；分配不依赖未来点击/求助。保留 matched pair，但单人内重复目标和有限随机化并不足以证明干预有效；严格效果研究仍需更多人、顺序平衡、足够样本。不能把已看到目标后的帮助结果解释为模型有效。

## 完整命令

```bash
cd /Users/audrey/Desktop/Phone
.venv/bin/python -m pip install -e '.[test,pilot,video]'
.venv/bin/python -m usercamera.pilot_design_v2
cd mobile_pilot
./gradlew testDebugUnitTest assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n org.usercamera.mobilepilot/.MainActivity
cd ..
# 手机停止并等待 Finalize 后，选择Session → 导出ZIP；保留到本机。
.venv/bin/python -m usercamera pilot-video-verify /path/to/session.zip --output reports/pilot_v2/new_check
.venv/bin/python -m usercamera pilot-replay /path/to/session.zip --output reports/pilot_v2/private/replay_new --allow-estimated-clock
# 浏览器打开生成的 index.html；若 file:// 限制视频，运行以下仅本机服务器：
.venv/bin/python -m http.server 8765 --bind 127.0.0.1 --directory reports/pilot_v2/private/replay_new
# 离线特征：不会把估计时钟标成可用于融合验证；须显式接受诊断估计。
.venv/bin/python -m usercamera pilot-prepare-inputs-v2 /path/to/session.zip --output reports/pilot_v2/private/features_new --allow-estimated-clock
.venv/bin/python -m usercamera pilot-evaluate-v2 --features reports/pilot_v2/private/features_new --output reports/pilot_v2/eval_new
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

`pilot-video-verify` 也支持原有真实 v1 JPEG Session，并报告忽略的 Finder `.DS_Store`；使用临时只读副本校验，不修改原始文件。

v2 模型名与旧 v1 分开：M0 Screen；M1 Screen+Actions；M2 +Single User Frame（16×12灰度弱输入）；M3 +Temporal User Features；M4 +Video Encoder（接口，未训练）；M5 +过去其他 trial 的 mismatched User（同一分区、同一 Session）。共享 participant/session 分组拆分、训练内预处理、验证集参数选择；M4 没有充分真实同步数据时不训练。Fixed prefixes 为1/2/3/5s，输入严格早于 cutoff 和第一次求助，标签为后续实际求助，不使用评分或已发生的 help_request 作输入。短任务及求助前缀被排除需单独报告选择偏差。单一参与者不报告跨用户泛化。未经验证的时钟直接阻止融合评估。

屏幕流默认重建式 UI timeline，包括任务 View、说明/问卷/暂停/休息的实际截图；没有实现 MediaProjection 捕获其他 App，未来只能经系统显式授权。没有训练 GUI Agent / GRPO。

API 依据：[CameraX Recorder](https://developer.android.com/media/camera/camerax/video-capture) 与 [MediaPipe Android Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/android)。公开 API 的 Start/Status 回调语义不足以证明曝光时间，因此此实现不宣称已完成物理同步验证。

功能试跑参与者编号使用 `device_smoke...`，无论过程中是否有人协助操作，均只用于设备验证，不能作为受控参与者数据。App 内对应按钮可不填写主观评分而继续。

10月29日修正：元素保存实际foreground gray / 背景ARGB / contrast，并另保留planned灰度；已用无相机模式完成真机回归。v2 GRU所有UI步均严格早于prefix cutoff，device-smoke/mock即便时钟标为usable也不能进入研究评估。当前包和10月27日视频实测包指纹分开，见RESULTS。
