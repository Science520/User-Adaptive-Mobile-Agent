"""Evidence-separated report; never relabel geometric residuals as prediction."""
import json
from pathlib import Path

from .io import read_jsonl, sha256


def generate_report(root="data", output="reports/mpii_geometry"):
    root, output = Path(root), Path(output)
    geometry = json.loads((output / "geometry_consistency.json").read_text())
    models = json.loads((output / "h1_models.json").read_text())
    audit = json.loads((root / "processed/mpii_audit.json").read_text())
    source_hash = sha256(root / "processed/mpii.jsonl")
    if geometry["input_sha256"] != source_hash or models["input_sha256"] != source_hash:
        raise ValueError("Geometry/model reports do not match current MPII schema/input")
    all_labels = geometry["all_local_annotations"]
    lines = ["# MPIIFaceGaze Camera–Screen Geometry Validation", "",
             "本次复用已有数据；未下载新数据集，未进行 GUI Agent 或 GRPO 训练。几何标注重建、真实图像预测和此前 H2/H3 合成实验分别解释。", "",
             "## 1. 数据完整性与坐标约定", "",
             f"本地完整标注 {audit['total_local_annotation_rows']:,} 行，格式错误 {audit['full_annotation_format_errors']}；实际照片子集 {audit['rows']} 张，15 名参与者各 24 张。其余标注没有对应本地图片是取样范围，不能算作损坏图片。",
             f"15 组 Camera / monitorPose / screenSize 均解析成功；图像无效 {len(audit['invalid'])}，计划取样缺失 {len(audit['missing_selected_images'])}。完整标注中 {all_labels['outside_display']} 个二维标签越出声明的屏幕范围；保留原值，不调整尺寸、不删除整天数据。", "",
             f"原始下载清单中的 {audit.get('original_manifest_files_sha256_verified',0)} 个文件已逐一核验 SHA-256；不匹配 {len(audit.get('original_manifest_file_mismatches',[]))}。", "",
             "- `Camera.mat`：K、畸变系数、标定 RMS。其 `rvecs/tvecs` 是相机标定棋盘的多视图姿态，不能用作屏幕外参。",
             "- `monitorPose.mat`：实际旋转字段为 `rvects`，同时兼容 `rvecs`。Rodrigues 旋转向量单位为弧度，平移与三维标注单位为 mm。",
             "- 列向量变换：`X_camera = R_screen_to_camera @ X_screen + t_screen_to_camera`；逆变换 `X_screen = R.T @ (X_camera - t)`。",
             "- 相机光心为原点，X 向图像右，Y 向图像下，Z 从相机朝前。屏幕有效显示区左上角为原点，x 向右、y 向下、z=0。",
             "- 连续像素换算 `x_px=x_mm*width_pixel/width_mm`、`y_px=y_mm*height_pixel/height_mm`；不使用 W−1、不补 1 px、不做轴翻转。方向与原点经全体 2D/3D 标注一致性检验支持，README 本身没有逐项明确这些约定。",
             "- 统一 Schema：`data/processed/mpii_calibrations.json`，样本内嵌 `calibration`；保留照片、六点、head rvec/translation、face center、3D gaze target、2D screen label。", "",
             "## 2. 几何标定一致性（不是 gaze 模型精度）", "",
             "从官方 face center 到官方 3D target 构造射线，再与外参定义的屏幕平面求交、逆变换、换算屏幕像素。这个过程使用了真实标签；它不是从图像预测 gaze。",
             f"360 张照片子集平均重建残差：{geometry['overall_reconstruction_px']['mean']:.6g} px，最大 {geometry['overall_reconstruction_px']['max']:.6g} px；平均物理残差 {geometry['overall_reconstruction_mm']['mean']:.6g} mm。",
             f"完整 {all_labels['n']:,} 行标注也可在无照片时检查几何关系：不一致 {all_labels['inconsistent']} 行，越界标签 {all_labels['outside_display']} 行。越界与几何不一致是两个独立诊断。", "",
             "| 参与者 | 全标注行数 | 几何均值 px | 几何最大 px | 越界标签 |", "| --- | ---: | ---: | ---: | ---: |"]
    for subject, values in all_labels["subjects"].items():
        m = values["reconstruction_px"]
        lines.append(f"| {subject} | {values['rows']} | {m['mean']:.3g} | {m['max']:.3g} | {values['outside_display']} |")
    lines += ["", "每名参与者另有错误旋转方向、错误原点、水平/垂直翻转、单位 ×10、1-based 偏移及 W−1 比例的诊断误差；这些候选只用于定位实现问题，未按测试标签选择或修正参数。见 `geometry_consistency.json`。微小残差也不能证明实际硬件标定独立精确，因为 3D/2D 标签本身可来自相同标定过程。", "",
              "## 3. 模型预测：participant-disjoint", "",
              f"{models['protocol']}。所有结果来自 360 张真实图像的 OOF 预测，每个参与者只在测试折出现一次。模型设置事先固定，没有根据测试误差选择 alpha、PCA 或 checkpoint。",
              "3D 指标为预测方向与官方方向的夹角。主 2D 指标使用独立的 normalized-screen 回归头，按各自屏幕尺寸还原 px/mm；不需要测试图像的 gaze target、真实 gaze direction 或真实 face center 作为输入。",
              "CNN 为冻结的 ImageNet-1K ResNet18，仅训练小型 Ridge 预测头；不是重现 gaze 专用 SOTA。face/eye crops 依赖给定六点，因此是带 oracle crop localization 的图像 appearance probe；head-pose 类模型也使用给定的估计标注，不等同于完整图像自动感知管道。", "",
              "| 模型 | 3D mean ° | 3D median ° | 2D mean px | 2D mean mm |", "| --- | ---: | ---: | ---: | ---: |"]
    for name, record in models["models"].items():
        m = record["metrics"]
        lines.append(f"| {name} | {m['angular_error_deg']['mean']:.3f} | {m['angular_error_deg']['median']:.3f} | {m['screen_direct_error_px']['mean']:.2f} | {m['screen_direct_error_mm']['mean']:.2f} |")
    lines += ["", "保留原始 32×24 像素 Ridge，其 gaze 误差应与归档第一阶段一致。原始报告见 `reports/archive_phase1/`，本次不覆盖其预测文件。", "",
              "射线投影另外分别报告：①模型预测 face center + 模型方向；②给定 face center + 模型方向。第二项是 **annotated-origin 条件诊断**，不能称作完全从图像预测的屏幕定位。无效/背向射线单独计数；有效射线上的误差不掩盖失败率。直接 screen head 和 ray head 也不保证彼此一致。", "",
              "| 模型 | 预测原点 ray mean mm（有效样本） | 预测原点无效射线 | 给定原点条件 ray mean mm | 给定原点无效射线 |", "| --- | ---: | ---: | ---: | ---: |"]
    for name, record in models["models"].items():
        m = record["metrics"]
        a, b = m["predicted_origin_ray"], m["annotated_origin_ray"]
        av, bv = a["error_mm_valid_only"]["mean"], b["error_mm_valid_only"]["mean"]
        av_text, bv_text = f"{av:.2f}" if av is not None else "N/A", f"{bv:.2f}" if bv is not None else "N/A"
        lines.append(f"| {name} | {av_text} | {a['invalid_count']}/{a['total']} | {bv_text} | {b['invalid_count']}/{b['total']} |")
    lines += ["", "## 4. 输入模态贡献", "",
              "下面为左模型减右模型的误差，负值表示左模型更好。区间按参与者配对 bootstrap；只重采样固定 OOF 误差，没有在每轮 bootstrap 重新训练，不作为正式显著性检验。", "",
              "| 对照 | Δ angular ° [95% interval] | Δ direct screen mm [95% interval] |", "| --- | ---: | ---: |"]
    for name, comparison in models.get("modality_comparisons", {}).items():
        a, b = comparison["angular_error_deg"], comparison["screen_direct_error_mm"]
        lines.append(f"| {name} | {a['mean_left_minus_right']:.3f} [{a['ci95'][0]:.3f}, {a['ci95'][1]:.3f}] | {b['mean_left_minus_right']:.3f} [{b['ci95'][0]:.3f}, {b['ci95'][1]:.3f}] |")
    lines += ["", "这组小样本结果不能预设融合越多一定越好。calibration 对确定性投影必需，但作为学习特征仍可能因参与者少和设备指纹而不能带来预测改善。", "",
              "## 5. 错误样本、可视化与迁移局限", "",
              "- `annotation_warnings.jsonl`：全部越界/几何异常标注的原始 ID、原因、是否有本地照片；均未改标签。",
              "- `geometry_errors.jsonl`：几何重建失败/超阈值样本，空文件表示在所列阈值下未发现异常。",
              "- `model_worst20.jsonl`：预先指定融合模型的 20 个最大角度误差样本；保留所有模型结果，未用于调参或筛选训练集。",
              "- `model_predictions.jsonl`：每个 OOF 样本的方向、直接屏幕预测、两种射线定位和失败原因。",
              "- `visualizations/index.html`：30 个真实样本的四面板图、15 名参与者的分布与误差图；原图/landmarks、已知屏幕 target、统一 3D 场景和模型误差分开显示。", ""]
    worst = read_jsonl(output / "model_worst20.jsonl")
    if worst:
        chosen = "appearance_head_pose_calibration_ridge" if "appearance_head_pose_calibration_ridge" in worst[0]["models"] else "landmarks_head_pose_ridge"
        lines += ["最差样本示例（不是自动删除清单）：", "", "| ID | 角度误差 ° | direct screen mm |", "| --- | ---: | ---: |"]
        for row in worst[:5]:
            r = row["models"][chosen]
            lines.append(f"| {row['id']} | {r['angular_error_deg']:.2f} | {r['screen_direct_error_mm']:.2f} |")
    lines += ["", "迁移局限：笔记本的固定 screen-camera 外参与手持手机的运动状态、相机安装位置、距离/视角分布不同；手机相机画面可能裁切、旋转或镜像，K 必须同步变换。face center 是脸模型中心，不是眼球中心；头姿和三维中心均为估计标注。当前没有独立距离真值、自动 landmark/head detector 失败率、连续时间信号或老年用户验证。ImageNet 视觉特征也未针对眼部细节和 gaze 域适配。尚不能从本实验推导真实 GUI 困难识别增益。", "",
              "## 6. 实际执行与剩余问题", "",
              "已成功运行的模型为上表全部行，运行环境、checkpoint 哈希、数据和代码哈希见 `run_manifest.json`；固定预处理的特征缓存记录在 `data/cache/mpii_cnn_features.json`。", "",
              "```bash", "# 隔离环境，仅首次增加依赖；已有数据不下载",
              "python3 -m venv --system-site-packages .venv",
              ".venv/bin/python -m pip install 'torch==2.2.2' 'torchvision==0.17.2'",
              "# 官方 ImageNet checkpoint，仅首次准备；已有文件复用",
              ".venv/bin/python -m usercamera mpii-weights",
              "# 只运行 MPII：本地解析 → 几何 → 模型 → 30 样本图 → 报告",
              "PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m usercamera mpii-run",
              "PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q", "```", "",
              "剩余问题：360 张采样的跨参与者统计不稳定；ImageNet 冻结 probe 不是 gaze 专用训练；需要独立的 landmark/head/origin 估计器以去除 oracle 条件。243 个越界标签尚无独立屏幕配置记录与本地图像用于逐张解释，因此只标记，不推断原因或修正标签。真实手机同步采集仍是检验 H2/H3 的必要步骤。", "",
              "## 7. 保留 H2 / H3 合成结果", "",
              "此前 `reports/h2_h3_synthetic.json`、`reports/synthetic_predictions.jsonl` 完整保留；本次未重新合成或重新评估。其中 distance 是模拟数值，不是本次 camera-derived feature。合成增益不能证明真实 camera stream 的互补价值。", ""]
    (output / "RESULTS.md").write_text("\n".join(lines))
    return str(output / "RESULTS.md")
