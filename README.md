本轮移动端视频升级：[Mobile Pilot v2](mobile_pilot/VIDEO_V2.md) · [构建与真机结果](reports/pilot_v2/RESULTS.md)。MPIIFaceGaze 既有结果保持不变。

# User-Camera Stream：公开数据与合成验证

本项目从 `thought2.md` / `thought3.md` 的第一阶段公开数据与合成验证扩展到受控手机时序Pilot。原文档保留不变，其中完整Agent、招募、后训练等设想没有作为开发指令执行。当前范围包括公开数据验证、手机采集原型、离线质量检查、因果时序基线和可复现报告。

**当前优先：Phase2 Temporal User–Screen Mobile Interaction Pilot。** 入口为 [mobile_pilot/README.md](mobile_pilot/README.md)、[采集协议](mobile_pilot/PILOT_PROTOCOL.md)、[数据Schema](mobile_pilot/SCHEMA.md)、[Pilot运行结果](reports/pilot/RESULTS.md)和[MPII720扩展对照](reports/mpii_expansion/RESULTS.md)。Android工程源码已生成；本机缺JDK/SDK，APK未编译、未真机验证。Python闭环已在明确标记mock的Session上测试，不能作为真实H2/H3证据。

已下载的扩展360张已整合到独立 `data/views/mpii_v2_720`，旧360样本、manifest、splits和历史报告不变。本轮不重新下载数据。新增命令：

```bash
.venv/bin/python -m usercamera mpii-integrate-expansion
.venv/bin/python -m usercamera mpii-eval-expanded
# 先查看reports/mpii_expansion/neural_resource_estimate.json；显式启用15折部分微调
.venv/bin/python -m usercamera mpii-eval-expanded --run-neural --max-epochs 12
.venv/bin/python -m usercamera pilot-build-stimuli
.venv/bin/python -m usercamera pilot-verify-session mobile_pilot/mock_sessions/mock_s00 --allow-mock
.venv/bin/python -m usercamera pilot-extract-features mobile_pilot/mock_sessions --backend mock --allow-mock
.venv/bin/python -m usercamera pilot-evaluate --allow-mock
.venv/bin/python -m usercamera pilot-report
```

真实导出Session使用另一个输出目录并移除 `--allow-mock`，feature backend换为mediapipe；完整构建/采集/导出/回放命令见mobile_pilot说明。默认不上传人脸数据；Manifest无网络权限。本轮采用带原始sensor/arrival时间的JPEG序列，不将MP4播放PTS当作单调时钟。没有可靠gaze时输出null，单目距离只为relative-scale proxy。

**上一轮：MPIIFaceGaze 越界审计、严格 LOSO 对照与粗粒度 user-state。** [结果](reports/MPII_NEXT_RESULTS.md)、[越界审计](reports/mpii_audit/outlier_summary.md)、此前[几何结果](reports/RESULTS.md)和[30个真实样本可视化](reports/mpii_geometry/visualizations/index.html)均保留。原始第一阶段H1/报告归档于 `reports/archive_phase1/`；H2/H3合成结果原文件保留。

## 上一轮 MPII 审计与模型入口（保留）

复用本地 360 张图像、15 人完整标注/calibration、已缓存 ImageNet 权重；默认不下载数据。四步共享 `reports/mpii_next/splits.json`：15折 LOSO，每折训练13人、验证1人、测试1人；所有 scaler/PCA 与超参选择仅使用训练/验证人。

```bash
cd /Users/audrey/Desktop/Phone
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m usercamera mpii-audit-outliers
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m usercamera mpii-compare-cleaning
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m usercamera mpii-strong-baselines --max-epochs 12
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m usercamera mpii-coarse-eval
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

`mpii-audit-outliers` 从全部原始 txt 独立重算边界、subject/day、几何一致性；输出 `reports/mpii_audit/{outliers.jsonl,outliers_by_day.csv,outlier_summary.md,figures/}`。连续屏幕边界与像素中心边界单独统计，不改官方标签。外部 pperle 源码固定版本保存在 `reference/`，其按图片位置对齐标注的假设不适用本地稀疏图像。

`mpii-compare-cleaning` 用 ID manifest 定义 Original / On-screen / Day-filtered；分别比较清理训练集与限制测试集。现有图片 A/B=360、C=350，没有越界标签照片，不能测试直接移除243条的收益。默认仅生成扩展计划：额外360张预计约42.59MiB，字节预算为硬上限。只有显式传 `--allow-download --download-budget-mib 64 --expansion-dir data/expansions/mpii_v1` 才请求新数据；新目录拒绝覆盖。扩展manifest尚未接入模型训练，本轮没有下载。

`mpii-strong-baselines` 保留低分辨率 Ridge；新增冻结224px face/eye Ridge、oracle/predicted pose诊断、known hardware calibration、64px matched frozen head与layer4微调。微调最多12 epoch、内部验证early stopping，两组lr/weight decay；156/312训练样本学习曲线均来自已有360张。各折缓存按源码、输入、训练/验证标签、配置指纹复用，测试标签在训练函数中置NaN。所有CNN仍使用**标注landmark crops**；oracle pose与预测pose分开，未实现全自动landmark检测。

`mpii-coarse-eval` 输出2×2/3×3/4×4与左中右Macro-F1、balanced accuracy、prior/chance基线、逐人表现，另测head pose和静态距离proxy。汇总写入 `reports/MPII_NEXT_RESULTS.md`。gaze zone不是困难标签；没有时间序列或真实困难识别结论。

全部新结果在 `reports/mpii_next/`。`strong/strong_results.json` 包含逐人指标/超参选择/成本，`prediction_errors.jsonl`、`invalid_rays.jsonl`、`worst20.jsonl`保留异常预测。ray使用预测origin，不用测试官方face center冒充预测；无效ray保留并报告覆盖率/失败惩罚，绝不只给有效子集平均。没有几何loss消融、完整骨干微调、gaze-specific架构或手机同步困难实验；局限和实际运行结果见本轮报告。

## 此前几何验证入口（保留）

现有数据全部复用，无需执行 `download`。本机隔离环境已安装 PyTorch 2.2.2 / torchvision 0.17.2，ImageNet ResNet18 权重已缓存。

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m usercamera mpii-run
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

该命令只执行 MPII 解析、几何一致性、participant-disjoint 模型、可视化和报告，不下载数据、不重跑 H2/H3、不训练 GUI Agent 或 GRPO。模型评估不会隐式下载权重；缺少 checkpoint 时明确报错。

分步命令：

```bash
.venv/bin/python -m usercamera mpii-prepare
.venv/bin/python -m usercamera mpii-geometry
.venv/bin/python -m usercamera mpii-models
.venv/bin/python -m usercamera mpii-visualize --count 30
.venv/bin/python -m usercamera mpii-report
```

仅在新环境首次准备依赖和 **模型权重**（不是数据集）：

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install 'torch==2.2.2' 'torchvision==0.17.2'
.venv/bin/python -m usercamera mpii-weights
```

也可 `pip install -e '.[geometry,test]'`。`mpii-weights` 检查现有 checkpoint 并复用，使用官方 ImageNet 权重以避免 gaze 专用预训练权重可能包含测试参与者。CNN backbone 冻结，只拟合小型线性头，crop 使用给定六点；这不是端到端自动 gaze tracker。

新增实现与输出：

| 文件 | 内容 |
| --- | --- |
| `usercamera/camera_screen_geometry.py` | 标定 schema、坐标变换、射线求交、全标注一致性与错误约定诊断 |
| `usercamera/mpii_models.py` | 保留 32×24 Ridge；landmark/head pose、冻结 face/eye CNN、appearance+pose+calibration 对照 |
| `usercamera/visualize_mpii.py` | 30 个真实样本四面板、15 名参与者分布、HTML 索引 |
| `data/processed/mpii_calibrations.json` | 15 组 K、畸变、屏幕 R/t、物理/像素尺寸、变换矩阵与源文件哈希 |
| `reports/mpii_geometry/geometry_consistency.json` | 360 照片子集及完整 37,667 行标注的几何残差；不是模型预测精度 |
| `reports/mpii_geometry/h1_models.json` | 10 个对照的 3D angular、2D px/mm、射线覆盖率、逐参与者与模态贡献 |
| `reports/mpii_geometry/annotation_warnings.jsonl` | 243 个越界标签，保留原值及是否有本地图片 |
| `reports/mpii_geometry/model_worst20.jsonl` | 预先指定融合模型的最大预测误差样本，未用于调参 |
| `reports/mpii_geometry/run_manifest.json` | 实际命令、成功模型、代码/数据/权重哈希与 H2/H3 保留校验 |

屏幕坐标约定是 `Xc=Rsc@Xs+tsc`，mm、Rodrigues radians、有效显示区左上原点、x 右/y 下。`monitorPose.mat` 真实字段为 `rvects`；`Camera.mat` 的多组 rvecs/tvecs 是棋盘姿态，不能用作屏幕外参。屏幕像素连续换算不加减 1、不手工翻转。全部 37,667 行几何一致，但 243 个标签越过声明的屏幕范围，这两类检查不能混淆。

主 2D 预测指标来自独立 screen 回归头；另外分别保存“预测 face center 的射线”和“给定 face center 的条件射线”。后者不能称作完全由图像得到的定位精度。参与者分组之外还需手机域独立采集；本数据是笔记本场景，三维 face center/pose 是估计标签。

## 第一阶段原始流程（保留，不是本轮默认入口）

Python 3.9+，无需 GPU、API Key 或付费模型。当前电脑已有所需运行库；可直接在 `Phone/` 中运行：

```bash
python3 -m usercamera --help
python3 -m usercamera run
python3 -m pytest -q
```

在新环境中安装：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
```

首次准备公开数据（需要网络）：

```bash
python3 -m usercamera download all --screens 48 --per-subject 24 --seed 42
python3 -m usercamera run
```

下载器从官方原始文件读取，不依赖 HF Viewer 或 `load_dataset()`。大 ZIP 用 HTTP Range 取样，每个远程 ZIP 默认限制传输 192 MiB；MobileViews 只下载约 45 MB 的官方单 App 示例。每个文件记录 SHA-256，ZIP 读取校验 CRC；下载目录保留来源与抽样清单。网络失败会明确报错，重跑复用已完成文件。Range 请求有缓存和流量上限，但不是整包断点续传。

分步执行：

```bash
python3 -m usercamera prepare
python3 -m usercamera h1
python3 -m usercamera grounding
python3 -m usercamera synthesize --config configs/synthetic.json
python3 -m usercamera evaluate
python3 -m usercamera report
```

`--data` 与 `--output` 可指定独立实验目录。`synthesize --no-render` 只生成数值样本，适合调试；常规运行会保存全部重绘图像与预览图。Linux 如没有中文字体，可用 `synthesize --font /path/to/NotoSansCJK-Regular.ttc`，配置里记录实际字体路径。

## 三个问题分别测什么

| 问题 | 已实现 | 不能据此声称 |
| --- | --- | --- |
| H1：Camera 可提取信息吗？ | MPIIFaceGaze 图像像素 → gaze 向量、头旋转、face-camera 距离代理；参与者分组 5 折；与训练集均值基线比较 | 手机场景可靠性、phone-eye 真实距离、连续行为变化已验证 |
| H2：User 信息能补充 Screen + Actions 吗？ | 合成几何参数 + UI 因子，比较 S / S+A / S+U / S+A+U / S+A+shuffled-U / prior 基线 | 随机公开人脸与 GUI 的真实同步关系，或真实用户上的增益 |
| H3：能判断 zoom / hint / none 吗？ | 单独训练与评估合成干预类别，报告无须干预样本上的错误干预率 | 干预改善了真实任务成功率或用户负担 |

第一阶段 H1 使用低分辨率像素 Ridge，原结果归档保留；新增 H1 对照见上面的几何入口。原始 Ridge 没有使用标注 gaze、头姿或距离作为输入。新增 pose 类对照会使用估计的 head pose，CNN crop 使用标注 landmarks；两者均明确标注辅助条件。MPIIFaceGaze 是笔记本域；抽样图像不是连续视频。

GUI 侧实现三件事：FunUI 四类中文原始任务读取；grounding 合法性与泄漏检查；MobileViews hierarchy 中的文本、bounds、可点击区域、屏幕密度提取。这里尚未训练 UI-Hawk 或 VLM。`grounding` 默认是**屏幕中心点的评分管道检查**，不代表 GUI 理解能力。

MobileViews 的 `actions.csv` 也会解析成动作—前后屏幕映射，并检查 CSV 顺序的状态断点。它是自动探索器轨迹，没有人类困难标签或 user-camera 流，缺少的时间戳不会伪造补齐。系统界面切换仍归入原 App 采集轨迹。官方示例的 state 宽高字段与实际图片不一致，适配器记录该问题并采用图片尺寸。

如已有 GUI 模型，可传入预测：

```bash
python3 -m usercamera grounding --predictions predictions.jsonl
```

预测格式为 `{"id":"ui_grounding_cn:123","point_px":[350,780]}`，ID 来自 `data/processed/funui_tasks.jsonl`。缺失预测计错；不存在的元素、越界框和问题内直接包含坐标的样本会单独记录并排除。QA/referring/summarization 目前只读取保留，尚未做模型评分。

## 合成定义

设实际字形高度为 `s` 个截图像素、像素密度为 `p` PPI、眼睛到屏幕距离为 `d` mm，在正视近似下：

$$h=\frac{25.4s}{p}\ \mathrm{mm},\qquad
\alpha=2\arctan\left(\frac{h}{2d}\right),\qquad
\alpha_{deg}=\frac{180}{\pi}\alpha.$$

代码在渲染时测量实际字体包围框高度，避免把 font size、sp/dp 或 hierarchy 容器高度当成字形高度。PPI、距离、字体、灰度、元素数量和阈值都写在 [configs/synthetic.json](configs/synthetic.json)。这些阈值是实验假设，**不是视力临床阈值**；字体、倾斜、偏心度与个体差异还未建模。

合成画面是受控重绘，不是对原截图“真实用户遇困”的标注。MobileViews 提供截断后的文本素材；FunUI 未提供文本转录的框使用明确标记的中文词表。文字后加唯一编号避免目标重复。每条样本保留原图哈希、App、来源、字体和变换参数。

- `visual`：视角小于阈值，或前景/背景对比度低于阈值。
- `navigation_proxy`：前两者不成立，但元素数量达到密度阈值；它只是搜索复杂度代理。
- `none`：以上代理条件均不成立。
- `hint`：低对比度优先，或仅界面拥挤；`zoom`：其余小视角样本；`none`：其余样本。

`U` 中距离是带噪声的模拟测量，head yaw/pitch 是无关模拟扰动；没有把 MPIIFaceGaze 的人脸拼进 GUI。Actions 也独立随机模拟，未从困难或结果派生。真实距离和计算出的视角只放在 `simulation_truth`，不进入特征矩阵。模型用渲染器元数据，并非学到的 screenshot embedding。

由于标签公式明确使用距离，融合增益在机制上是预期的。该实验用于检查管道和预设几何机制，不能作为论文中“摄像头互补信息”的核心证据。

## 评估约束

所有合成变体按**源 App**整体分折；相同源屏幕 ID / 图像哈希若跨组会报错。H1 按**参与者**分折。预处理仅在训练折拟合；User 打乱对照分别在训练/测试折内部执行。固定模型参数，报告 OOF Macro-F1、balanced accuracy、AUROC、ECE、混淆矩阵、组级配对 bootstrap 区间。区间没有重新训练每次 bootstrap，按描述性不确定性解释，不宣称正式显著性结论。ECE 未经概率校准。

真实同步数据另有接口：

```bash
python3 -m usercamera pilot pilot_windows.jsonl --validate-only
python3 -m usercamera pilot pilot_windows.jsonl --group-by subject_id
python3 -m usercamera pilot pilot_windows.jsonl --group-by app_id
```

格式与后续判定标准见 [docs/PILOT_PROTOCOL.md](docs/PILOT_PROTOCOL.md)。当前没有采集用户、开启摄像头或上传数据。

## 文件

| 路径 | 内容 |
| --- | --- |
| `usercamera/` | 下载、适配、几何、合成、评估、CLI |
| `data/raw/*/manifest.json` | 真实来源、采样、哈希 |
| `data/processed/audit.json` | 数据质量检查 |
| `data/processed/mpii.jsonl` | 标准化人脸样本与标签 |
| `data/processed/screens.jsonl` | 标准化截图、元素与来源 |
| `data/processed/screen_features.jsonl` | hierarchy 尺寸、点击区域、密度 |
| `data/processed/mobileviews_actions.jsonl` | 真实公开探索器的动作、前后状态映射、连续片段 |
| `data/processed/funui_tasks.jsonl` | 四类任务，保留原标注 |
| `data/synthetic/scenarios.jsonl` | 代理样本与模拟真值分栏保存 |
| `data/synthetic/contact_sheet.png` | 合成截图预览 |
| `reports/` | 实际指标、OOF 预测、分折清单、环境与中文报告 |
| `tests/` | 几何单位、因果时间、分组泄漏、缺失预测、下载边界检查 |

来源与许可见 [docs/SOURCES.md](docs/SOURCES.md)。本项目未重新分发数据；`data/raw/processed/synthetic` 不进入版本管理。
