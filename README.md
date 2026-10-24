# User-Camera Stream：公开数据与合成验证

本项目是 `thought2.md` / `thought3.md` 的第一阶段实验实现。原文档保留不变，文档里的完整 Agent、招募、后训练等设想没有作为本次开发指令执行。本次范围是：真实公开数据取样、质量检查、图像基线、合成代理任务、分组消融和可复现报告。

**最先阅读实际结果：[reports/RESULTS.md](reports/RESULTS.md)。合成增益不能证明真实摄像头有用。**

## 运行

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

H1 使用低分辨率像素 Ridge 作为可解释、CPU 可运行的诊断基线，没有复现 SOTA gaze encoder，也没有使用标注 gaze、头姿或距离作为输入。头姿和 face center 本身是数据集提供的估计标注。MPIIFaceGaze 是笔记本域；抽样图像不是连续视频。

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
