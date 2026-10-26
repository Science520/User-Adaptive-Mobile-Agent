# Temporal User–Screen Mobile Interaction Pilot

这是现有 `usercamera` 的研究原型扩展：同一台 Android 手机显示受控任务，记录前摄帧、UI状态、触摸和任务后自评。仅操作自己的实验App，无跨App自动化、MediaProjection、真实账户或支付。

**当前交付状态：Python闭环与mock测试已实际运行；完整Android工程已生成，但本机缺少JDK与Android SDK，APK未编译、未安装、未真机验证。** 实际构建失败日志在 [`../reports/pilot/android_build_attempt.log`](../reports/pilot/android_build_attempt.log)。68项Python测试通过；原生JUnit源码已提供但未运行。完整结果见 [`../reports/pilot/RESULTS.md`](../reports/pilot/RESULTS.md) 和 [`../reports/mpii_expansion/RESULTS.md`](../reports/mpii_expansion/RESULTS.md)。

## 已有数据扩展

不需要下载。原始360张和扩展360张已逐项核对manifest、路径、大小、SHA256和解码；新图有3个越界标签、16张位于异常采集日。新视图720张：Original720、On-screen717、Day-filtered694。原始标签全部保留。

```bash
cd /Users/audrey/Desktop/Phone
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m usercamera mpii-integrate-expansion
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m usercamera mpii-eval-expanded
cat reports/mpii_expansion/neural_resource_estimate.json
# 显式启用完整15折部分微调；预计约52分钟CPU、约600MiB内存，早停与机器负载会改变实际耗时
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m usercamera mpii-eval-expanded --run-neural --max-epochs 12
```

新视图位于 `data/views/mpii_v2_720/`，不改旧 `data/processed/mpii.jsonl`、manifest、splits或报告。主对照在相同旧360测试图、每折相同24张验证图上，仅训练312→624。额外360测试另报；没有把测试集变化当作改善。12epoch旧微调控制组只有在训练器源码、train/val/test IDs完全匹配时才复用，旧版未保存checkpoint，故旧控制模型在新增360测试图上的预测明确未计算。

## Android构建

版本为可复现固定组合：AGP8.7.3、Gradle8.9、Kotlin/Compose compiler2.0.21、Compose BOM2024.12.01、CameraX1.4.1、compile/target SDK35、minSDK26、JDK17。这些是固定版本，不宣称是最新版本。

1. 用 Android Studio 打开本目录 `mobile_pilot/`。
2. 在IDE选择JDK17并安装Android SDK Platform35。通过SDK Manager完成，不由本项目自动下载SDK。
3. 设置 `local.properties` 的 `sdk.dir=/你的/Android/sdk`，或 `ANDROID_HOME`。`local.properties` 已忽略。
4. 同步Gradle；首次同步会下载Gradle和Maven依赖，需要网络。

```bash
cd /Users/audrey/Desktop/Phone/mobile_pilot
./gradlew testDebugUnitTest assembleDebug
# 连接自己的Android设备、启用USB调试后才执行
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Wrapper文件已提供且distribution SHA256固定。本机执行 `./gradlew --offline testDebugUnitTest assembleDebug` 实际因缺JDK失败，因此不能认为源码已通过Android编译检查。没有生成APK。

## 手机采集与导出

1. 输入匿名Participant ID和新的Session ID；Session路径自动添加Participant前缀，禁止覆盖旧Session。
2. 指定随机种子和注视重复次数2或3。可以填入独立量具测得距离mm；留空即未测量，绝不自动当成相机距离真值。
3. 点前摄Start，先授予Camera权限；再点Start开始。若拒绝权限、设备无前摄或CameraX绑定失败，界面明确提示。可显式选择无相机开始，Camera缺失会记录。
4. Task A按随机顺序显示25个注视点，每点计划1500ms。实际draw onset、offset、屏幕全局像素坐标与view局部坐标均保存。它们是instructed targets，不是独立眼动真值。
5. Task B有48个中文视觉搜索任务。按指令点击目标；误点留在当前界面，正确点击或30秒超时后进入自评。帮助按钮只记录请求，不实施帮助。
6. 每个搜索trial后主动填写四项自评，没有预选答案。完成时间、成功、误点和帮助请求独立于自评保存。
7. Pause会把当前trial标记aborted；恢复以新attempt重做该trial，不拼接暂停前后为连续轨迹。Stop保存并结束。Activity转入后台时，正在采集的trial也会暂停。
8. 停止后选择Session，导出ZIP到用户选定位置。原始前摄帧、真实App绘制快照和JSON日志均在ZIP中。删除单个Session需在App确认；不会删除已导出的ZIP。

所有数据默认写入App私有目录，Manifest没有INTERNET权限。ZIP是用户主动导出。卸载App也会丢失未导出的本地数据。原型尚不支持被系统强杀后的自动续录；不完整Session将被校验拒绝，需保留原包排查，不能补造结束时间。

## 时钟与前摄方案

采用单一CameraX ImageAnalysis，将采样帧保存为JPEG序列，目标保存频率10Hz、请求640×480；实际分辨率与FPS以设备日志为准。没有绑定VideoCapture，因此不假称已验证MP4录制与ImageAnalysis的并发支持。

UI/trial/feedback使用 `elapsedRealtimeNanos()`；触摸 `eventTime` 属于uptime时钟，通过夹取elapsed/uptime读数映射并记录误差界。Camera2报告REALTIME时使用传感器原始capture时间；UNKNOWN时预热取arrival-sensor偏移下包络，但最小流水线延迟不可辨识，映射始终是estimated_unvalidated。默认不将其用于已同步融合；须另有独立capture-clock anchors验证。

日志保留sensor、arrival、stored、mapped时间。实际保存FPS、采样略过、写失败和推定帧缺口均报告。KEEP_ONLY_LATEST的真实driver丢帧数未知，不用推定缺口冒充精确值。draw callback仅为提交时间，不等于物理屏幕发光时刻。

## 主机端闭环

首次新环境：`pip install -e '.[geometry,pilot,test]'`；当前隔离环境依赖已准备。MediaPipe模型仅本地推理，不上传图像。

```bash
cd /Users/audrey/Desktop/Phone
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m usercamera pilot-build-stimuli

# 已提供4个明确标记mock的Session。重新生成时使用新目录，禁止覆盖
# .venv/bin/python -m usercamera pilot-build-stimuli --mock-output data/pilot_mock_v2

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m usercamera pilot-verify-session mobile_pilot/mock_sessions/mock_s00 --allow-mock
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m usercamera pilot-extract-features mobile_pilot/mock_sessions --backend mock --allow-mock
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m usercamera pilot-evaluate --allow-mock
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m usercamera pilot-report
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

真实设备导出后，替换路径；与mock使用不同输出目录，禁止混合两种证据层：

```bash
.venv/bin/python -m usercamera pilot-verify-session data/pilot_imports/my_session.zip --output reports/pilot_real
.venv/bin/python -m usercamera pilot-extract-features data/pilot_imports/my_session.zip \
  --output reports/pilot_real --backend mediapipe \
  --model data/models/face_landmarker.task \
  --detector-model data/models/blaze_face_short_range.tflite
.venv/bin/python -m usercamera pilot-evaluate --features reports/pilot_real/features --output reports/pilot_real
.venv/bin/python -m usercamera pilot-report --output reports/pilot_real

# 将实际使用的App PNG及真实像素元数据重新导出，不用Pillow重绘冒充像素一致
.venv/bin/python -m usercamera pilot-build-stimuli --session data/pilot_imports/my_session.zip --output data/pilot_ui_replay
```

模型权重已缓存在本机 `data/models/`。新机器若没有权重，可从[官方FaceLandmarker模型](https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task)和[官方短程FaceDetector](https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite)自行保存到上述路径；CLI不隐式下载。来源与SHA256记录于 `reports/pilot/reference_downloads.json`。Mac的MediaPipe即便CPU inference也可能需要桌面图形上下文；本机沙盒内初始化失败，正常OS图形权限下单图冒烟成功，详见 `mediapipe_smoke.json`。

FaceLandmarker不返回可直接使用的眼点visibility；字段null，另存“眼点在图像内比例”proxy。未供单独FaceDetector时检测分数也为null，阈值不能冒充返回概率。头姿来自canonical-face transform而非动捕；距离仅为相对face scale proxy。没有可靠校准的gaze时保留null，不以头朝向代替gaze。

## 分析边界

M0–M5复用S/A/U模态消融思路；新增真实时间窗口与GRU。固定prefix只读取cutoff前capture且已available的帧/动作；trial标签不传播为帧级困难起点。相对scale基准取当时已见的首个有效帧，不读取任务后半段。S/A/U特征白名单不包含outcome、反馈或future动作。

单人至少3个Session，按Session留出并设独立验证组；多人至少3人才能同时设participant-disjoint训练/验证/测试。重复UI模板跨partition时purge，数据不足则明确拒绝评估。App在Session内记录有效种子并随机排列干扰词位置；仍需检查重复模板，不把相邻trial/窗口随机打散。

mock数据含程序生成图案和伪造观测，仅用于IO、同步与泄漏测试。M0–M5、三种模型和四种窗口的mock分数不是H2证据。自评帮助偏好不是H3效果；本轮没有干预实验。Task C/D暂未实现，先完成A/B真机验证。

格式见 [SCHEMA.md](SCHEMA.md)，采集/分析协议见 [PILOT_PROTOCOL.md](PILOT_PROTOCOL.md)。旧 `docs/PILOT_PROTOCOL.md` 与 `pilot`命令保留，属于旧feature-table接口；本轮使用 `pilot-window-v2` 和上述新命令。
