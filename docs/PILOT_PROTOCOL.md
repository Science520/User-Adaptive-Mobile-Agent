# 从公开数据到同步 pilot 的判定边界

第一阶段的公开单模态数据不能检验真实 H2/H3。下面是后续可直接接入当前评估器的最小协议；这不是已经完成的用户实验，也不自动启动招募或采集。

## H1 独立检验

对同一个手机与参与者，使用已知 fixation target 测 gaze；用独立量具或标定装置测 eye–screen distance；用独立姿态参考测头姿。报告检测失败率、gaze 角度/屏幕误差、distance MAE、head rotation error。按参与者、设备、距离、照明分层，并记录校准条件。MPIIFaceGaze 的 face center norm 不替代 eye–screen 距离真值。

## H2 独立检验

同一参与者执行同一任务时，用共同单调时钟记录 user camera、screen、touch/actions。每个预测窗口只使用预测时间及以前的信息；任务最终结果、窗口之后的 back/zoom、自评不能作为输入。相邻窗口属于同一 trajectory，整体放进同一分组。

困难标签来自窗口相关的自评与独立标注；任务 outcome 单独存储，用于一致性检查，不能把“失败”直接等同于“看不清”。不要用 distance/gaze/hesitation 公式给真实标签，再将同样的特征输入模型。至少保留 none、visual、motor、navigation、semantic、cognitive_overload，可多标注者评估一致性。当前基线支持单主类，多标签扩展需另行定义评分。

分别做 held-out participant 与 held-out app 评估（两者都运行，不能用其中一个冒充另一个）。当前接口各需至少 3 组；pilot 样本量应根据实测效应、方差与研究设计进一步确定，而非凭合成 F1 推定。

预先固定特征提取器、模型与阈值，或使用独立验证集选择。比较 S、S+A、S+U、S+A+U、打乱 User 对照；除 AUROC/F1 外记录缺失模态、失败率、概率校准和亚组误差。参与者或 App 内相关性必须保留在不确定性估计中。

## H3 独立检验

先请独立标注者在不查看合成规则的情况下标注 none / zoom / hint，并分别评分。视觉困难不一定适合 zoom，界面拥挤也不等同于导航困难。模型预测类别好不代表真的改善交互。

后续干预效果需随机化/交叉条件等受控设计，比较任务成功、用时、错误、主观负担及不必要干预率，并控制练习与顺序效应。是否提前干预、干预延迟和无须干预的判定也应事先约定。

## 输入格式

每行 JSON，示例仅说明 schema，**不可把示例当作真实 pilot 数据**：

```json
{
  "id": "p01:task01:w0001",
  "evidence_tier": "real_synchronized",
  "subject_id": "p01",
  "app_id": "com.example.app",
  "trajectory_id": "p01:task01",
  "camera_stream_id": "local-recording-camera-id",
  "screen_stream_id": "local-recording-screen-id",
  "clock": "common_monotonic_ms",
  "input_start_ms": 0,
  "input_end_ms": 5000,
  "label_time_ms": 5000,
  "camera_timestamp_ms": 4990,
  "screen_timestamp_ms": 4980,
  "action_cutoff_ms": 5000,
  "screen": {
    "glyph_height_px": 26,
    "contrast_ratio": 5.2,
    "element_count": 18,
    "target_x": 0.5,
    "target_y": 0.3
  },
  "actions": {"elapsed_s": 5.0, "clicks": 1, "backs": 0},
  "user": {"distance_estimate_mm": 350, "head_yaw_deg": 3, "head_pitch_deg": -4},
  "difficulty": "visual",
  "difficulty_label_source": "self_report",
  "intervention": "zoom",
  "intervention_label_source": "independent_annotator"
}
```

screen 参数必须来自当时可得的观测或已知实验条件；真实 OCR 字形高度与 hierarchy 容器高度不能混用。目标位置应来自事先指令/任务定义，不能用事后的用户点击反推。User 中的距离必须是摄像头测量输出，不是隐藏实验真值。当前表格基线没有实现 temporal encoder，窗口特征是汇总量。

校验器检查显式证据层、非空流 ID、共同单调时钟、≤100ms camera/screen 对齐、因果截断、唯一 ID、trajectory 归属和独立标签来源。它无法仅凭字符串验证实际录像同步、标注真实性或同意情况；必须抽查原始数据。缺失观测需单独设计失败处理，当前接口会拒绝非有限特征。
