# MPIIFaceGaze Camera–Screen Geometry Validation

本次复用已有数据；未下载新数据集，未进行 GUI Agent 或 GRPO 训练。几何标注重建、真实图像预测和此前 H2/H3 合成实验分别解释。

## 1. 数据完整性与坐标约定

本地完整标注 37,667 行，格式错误 0；实际照片子集 360 张，15 名参与者各 24 张。其余标注没有对应本地图片是取样范围，不能算作损坏图片。
15 组 Camera / monitorPose / screenSize 均解析成功；图像无效 0，计划取样缺失 0。完整标注中 243 个二维标签越出声明的屏幕范围；保留原值，不调整尺寸、不删除整天数据。

原始下载清单中的 465 个文件已逐一核验 SHA-256；不匹配 0。

- `Camera.mat`：K、畸变系数、标定 RMS。其 `rvecs/tvecs` 是相机标定棋盘的多视图姿态，不能用作屏幕外参。
- `monitorPose.mat`：实际旋转字段为 `rvects`，同时兼容 `rvecs`。Rodrigues 旋转向量单位为弧度，平移与三维标注单位为 mm。
- 列向量变换：`X_camera = R_screen_to_camera @ X_screen + t_screen_to_camera`；逆变换 `X_screen = R.T @ (X_camera - t)`。
- 相机光心为原点，X 向图像右，Y 向图像下，Z 从相机朝前。屏幕有效显示区左上角为原点，x 向右、y 向下、z=0。
- 连续像素换算 `x_px=x_mm*width_pixel/width_mm`、`y_px=y_mm*height_pixel/height_mm`；不使用 W−1、不补 1 px、不做轴翻转。方向与原点经全体 2D/3D 标注一致性检验支持，README 本身没有逐项明确这些约定。
- 统一 Schema：`data/processed/mpii_calibrations.json`，样本内嵌 `calibration`；保留照片、六点、head rvec/translation、face center、3D gaze target、2D screen label。

## 2. 几何标定一致性（不是 gaze 模型精度）

从官方 face center 到官方 3D target 构造射线，再与外参定义的屏幕平面求交、逆变换、换算屏幕像素。这个过程使用了真实标签；它不是从图像预测 gaze。
360 张照片子集平均重建残差：1.85016e-06 px，最大 4.28249e-06 px；平均物理残差 3.8453e-07 mm。
完整 37,667 行标注也可在无照片时检查几何关系：不一致 0 行，越界标签 243 行。越界与几何不一致是两个独立诊断。

| 参与者 | 全标注行数 | 几何均值 px | 几何最大 px | 越界标签 |
| --- | ---: | ---: | ---: | ---: |
| p00 | 2927 | 1.73e-06 | 3.51e-06 | 0 |
| p01 | 2904 | 1.91e-06 | 3.78e-06 | 0 |
| p02 | 2916 | 1.74e-06 | 3.46e-06 | 5 |
| p03 | 2929 | 1.97e-06 | 4.56e-06 | 0 |
| p04 | 2860 | 1.71e-06 | 3.54e-06 | 0 |
| p05 | 2870 | 1.94e-06 | 4.12e-06 | 0 |
| p06 | 2877 | 1.96e-06 | 4.17e-06 | 0 |
| p07 | 2843 | 1.96e-06 | 4.28e-06 | 228 |
| p08 | 2767 | 1.94e-06 | 4.01e-06 | 0 |
| p09 | 2719 | 1.94e-06 | 3.95e-06 | 0 |
| p10 | 2194 | 1.94e-06 | 4.18e-06 | 10 |
| p11 | 2262 | 1.75e-06 | 3.72e-06 | 0 |
| p12 | 1601 | 1.76e-06 | 3.52e-06 | 0 |
| p13 | 1498 | 1.73e-06 | 3.6e-06 | 0 |
| p14 | 1500 | 1.93e-06 | 4.1e-06 | 0 |

每名参与者另有错误旋转方向、错误原点、水平/垂直翻转、单位 ×10、1-based 偏移及 W−1 比例的诊断误差；这些候选只用于定位实现问题，未按测试标签选择或修正参数。见 `geometry_consistency.json`。微小残差也不能证明实际硬件标定独立精确，因为 3D/2D 标签本身可来自相同标定过程。

## 3. 模型预测：participant-disjoint

fixed 5-fold GroupKFold by participant; train-only scaling/PCA and Ridge alpha=100; no tuning on test。所有结果来自 360 张真实图像的 OOF 预测，每个参与者只在测试折出现一次。模型设置事先固定，没有根据测试误差选择 alpha、PCA 或 checkpoint。
3D 指标为预测方向与官方方向的夹角。主 2D 指标使用独立的 normalized-screen 回归头，按各自屏幕尺寸还原 px/mm；不需要测试图像的 gaze target、真实 gaze direction 或真实 face center 作为输入。
CNN 为冻结的 ImageNet-1K ResNet18，仅训练小型 Ridge 预测头；不是重现 gaze 专用 SOTA。face/eye crops 依赖给定六点，因此是带 oracle crop localization 的图像 appearance probe；head-pose 类模型也使用给定的估计标注，不等同于完整图像自动感知管道。

| 模型 | 3D mean ° | 3D median ° | 2D mean px | 2D mean mm |
| --- | ---: | ---: | ---: | ---: |
| train_mean | 12.370 | 11.856 | 442.62 | 92.04 |
| pixels32x24_ridge | 14.635 | 12.959 | 556.88 | 115.18 |
| landmarks_only_ridge | 11.316 | 10.739 | 442.31 | 91.91 |
| head_pose_only_ridge | 11.288 | 10.665 | 441.15 | 91.66 |
| landmarks_head_pose_ridge | 11.274 | 10.671 | 441.56 | 91.73 |
| calibration_only_ridge | 12.141 | 11.479 | 449.84 | 93.57 |
| face_cnn_ridge | 12.923 | 12.264 | 452.89 | 93.98 |
| face_eye_cnn_ridge | 12.241 | 11.993 | 429.14 | 89.20 |
| appearance_head_pose_ridge | 11.063 | 10.548 | 427.92 | 88.89 |
| appearance_head_pose_calibration_ridge | 11.199 | 10.854 | 440.37 | 91.42 |

保留原始 32×24 像素 Ridge，其 gaze 误差应与归档第一阶段一致。原始报告见 `reports/archive_phase1/`，本次不覆盖其预测文件。

射线投影另外分别报告：①模型预测 face center + 模型方向；②给定 face center + 模型方向。第二项是 **annotated-origin 条件诊断**，不能称作完全从图像预测的屏幕定位。无效/背向射线单独计数；有效射线上的误差不掩盖失败率。直接 screen head 和 ray head 也不保证彼此一致。

| 模型 | 预测原点 ray mean mm（有效样本） | 预测原点无效射线 | 给定原点条件 ray mean mm | 给定原点无效射线 |
| --- | ---: | ---: | ---: | ---: |
| train_mean | 94.38 | 0/360 | 104.64 | 0/360 |
| pixels32x24_ridge | 125.19 | 2/360 | 122.12 | 0/360 |
| landmarks_only_ridge | 94.00 | 0/360 | 94.94 | 0/360 |
| head_pose_only_ridge | 93.78 | 0/360 | 94.70 | 0/360 |
| landmarks_head_pose_ridge | 94.00 | 0/360 | 94.54 | 0/360 |
| calibration_only_ridge | 94.44 | 0/360 | 102.69 | 0/360 |
| face_cnn_ridge | 95.36 | 0/360 | 110.10 | 0/360 |
| face_eye_cnn_ridge | 90.94 | 0/360 | 104.21 | 0/360 |
| appearance_head_pose_ridge | 90.75 | 0/360 | 93.48 | 0/360 |
| appearance_head_pose_calibration_ridge | 92.91 | 0/360 | 94.93 | 0/360 |

## 4. 输入模态贡献

下面为左模型减右模型的误差，负值表示左模型更好。区间按参与者配对 bootstrap；只重采样固定 OOF 误差，没有在每轮 bootstrap 重新训练，不作为正式显著性检验。

| 对照 | Δ angular ° [95% interval] | Δ direct screen mm [95% interval] |
| --- | ---: | ---: |
| landmarks_head_pose_ridge minus pixels32x24_ridge | -3.361 [-6.338, -1.505] | -23.454 [-46.065, -9.274] |
| landmarks_head_pose_ridge minus head_pose_only_ridge | -0.014 [-0.114, 0.086] | 0.069 [-0.467, 0.754] |
| face_eye_cnn_ridge minus face_cnn_ridge | -0.682 [-1.153, -0.237] | -4.787 [-7.354, -1.866] |
| appearance_head_pose_ridge minus face_eye_cnn_ridge | -1.178 [-1.668, -0.682] | -0.311 [-1.945, 1.351] |
| appearance_head_pose_calibration_ridge minus appearance_head_pose_ridge | 0.136 [-0.143, 0.426] | 2.530 [0.634, 4.644] |
| appearance_head_pose_calibration_ridge minus landmarks_head_pose_ridge | -0.075 [-0.704, 0.609] | -0.312 [-3.626, 3.139] |

这组小样本结果不能预设融合越多一定越好。calibration 对确定性投影必需，但作为学习特征仍可能因参与者少和设备指纹而不能带来预测改善。

## 5. 错误样本、可视化与迁移局限

- `annotation_warnings.jsonl`：全部越界/几何异常标注的原始 ID、原因、是否有本地照片；均未改标签。
- `geometry_errors.jsonl`：几何重建失败/超阈值样本，空文件表示在所列阈值下未发现异常。
- `model_worst20.jsonl`：预先指定融合模型的 20 个最大角度误差样本；保留所有模型结果，未用于调参或筛选训练集。
- `model_predictions.jsonl`：每个 OOF 样本的方向、直接屏幕预测、两种射线定位和失败原因。
- `visualizations/index.html`：30 个真实样本的四面板图、15 名参与者的分布与误差图；原图/landmarks、已知屏幕 target、统一 3D 场景和模型误差分开显示。

最差样本示例（不是自动删除清单）：

| ID | 角度误差 ° | direct screen mm |
| --- | ---: | ---: |
| Data/p08/day19/0024.jpg | 32.50 | 196.72 |
| Data/p03/day62/0107.jpg | 30.00 | 191.23 |
| Data/p08/day40/0509.jpg | 28.73 | 160.21 |
| Data/p03/day49/0485.jpg | 28.00 | 185.71 |
| Data/p07/day10/0001.jpg | 26.50 | 168.92 |

迁移局限：笔记本的固定 screen-camera 外参与手持手机的运动状态、相机安装位置、距离/视角分布不同；手机相机画面可能裁切、旋转或镜像，K 必须同步变换。face center 是脸模型中心，不是眼球中心；头姿和三维中心均为估计标注。当前没有独立距离真值、自动 landmark/head detector 失败率、连续时间信号或老年用户验证。ImageNet 视觉特征也未针对眼部细节和 gaze 域适配。尚不能从本实验推导真实 GUI 困难识别增益。

## 6. 实际执行与剩余问题

已成功运行的模型为上表全部行，运行环境、checkpoint 哈希、数据和代码哈希见 `run_manifest.json`；固定预处理的特征缓存记录在 `data/cache/mpii_cnn_features.json`。

```bash
# 隔离环境，仅首次增加依赖；已有数据不下载
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install 'torch==2.2.2' 'torchvision==0.17.2'
# 官方 ImageNet checkpoint，仅首次准备；已有文件复用
.venv/bin/python -m usercamera mpii-weights
# 只运行 MPII：本地解析 → 几何 → 模型 → 30 样本图 → 报告
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m usercamera mpii-run
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

剩余问题：360 张采样的跨参与者统计不稳定；ImageNet 冻结 probe 不是 gaze 专用训练；需要独立的 landmark/head/origin 估计器以去除 oracle 条件。243 个越界标签尚无独立屏幕配置记录与本地图像用于逐张解释，因此只标记，不推断原因或修正标签。真实手机同步采集仍是检验 H2/H3 的必要步骤。

## 7. 保留 H2 / H3 合成结果

此前 `reports/h2_h3_synthetic.json`、`reports/synthetic_predictions.jsonl` 完整保留；本次未重新合成或重新评估。其中 distance 是模拟数值，不是本次 camera-derived feature。合成增益不能证明真实 camera stream 的互补价值。
