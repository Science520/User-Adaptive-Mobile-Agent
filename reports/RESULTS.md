# 第一阶段实验结果

本报告由实际运行生成。公开单模态验证、合成代理任务和真实同步实验分别记录。

## 数据检查

```json
{
  "funui": {
    "screen_qa_cn_all_rows": 5525,
    "sampled_task_rows": 353,
    "screen_summarization_cn_all_rows": 2150,
    "ui_grounding_cn_all_rows": 3124,
    "grounding_out_of_screen_boxes": 0,
    "grounding_positive": 84,
    "grounding_negative_or_nonbox": 0,
    "grounding_question_contains_box": 3,
    "ui_referring_cn_all_rows": 3369,
    "screens": 48,
    "apps": 22
  },
  "mobileviews": {
    "screens": 266,
    "invalid": [],
    "apps": 1,
    "state_metadata_size_mismatches": 266,
    "action_rows": 1075,
    "action_audit": {
      "unmapped_from_states": 0,
      "unmapped_to_states": 0,
      "type_intent": 41,
      "csv_sequence_discontinuities": 1,
      "type_touch": 708,
      "type_kill_app": 39,
      "type_scroll": 100,
      "type_select": 32,
      "type_unselect": 34,
      "type_long_touch": 59,
      "type_set_text": 62
    },
    "has_synchronized_user_camera": false
  },
  "mpiifacegaze": {
    "rows": 360,
    "subjects": {
      "p00": 24,
      "p01": 24,
      "p02": 24,
      "p03": 24,
      "p04": 24,
      "p05": 24,
      "p06": 24,
      "p07": 24,
      "p08": 24,
      "p09": 24,
      "p10": 24,
      "p11": 24,
      "p12": 24,
      "p13": 24,
      "p14": 24
    },
    "invalid": [],
    "missing_selected_images": [],
    "distance_is_ground_truth": false,
    "real_temporal_stream": false
  }
}
```

## H1：公开人脸图像基线

360 张图像，15 名参与者，按参与者分组交叉验证。输入仅为低分辨率灰度像素。

| 指标（越低越好） | 图像 Ridge | 训练集均值基线 |
| --- | ---: | ---: |
| gaze_angular_error_deg | 14.6351 | 12.3702 |
| head_rotation_error_deg_estimated_label | 21.9628 | 16.1870 |
| face_camera_distance_proxy_absolute_error_mm | 80.3776 | 74.9672 |
| normalized_xy_error_unit_square_diagonal | 0.3502 | 0.2719 |

这只记录图像基线的误差；不据此宣称手机摄像头可靠性成立。头姿/距离代理标签来自估计，距离不是手机—眼睛距离真值。

## H2 / H3：合成代理验证

1632 条源于公开界面素材的受控重绘样本。User 特征为模拟几何量，没有将随机人脸与屏幕配成真实数据。

距离进入了代理标签公式，因此性能提升只能验证预设机制和实验管道。

### difficulty

| 模态 | Macro-F1 | Balanced acc. | AUROC | ECE |
| --- | ---: | ---: | ---: | ---: |
| S | 0.819 | 0.898 | 0.973 | 0.064 |
| S+A | 0.827 | 0.899 | 0.971 | 0.067 |
| S+U | 0.961 | 0.982 | 0.998 | 0.108 |
| S+A+U | 0.958 | 0.978 | 0.998 | 0.108 |
| S+A+shuffled_U | 0.828 | 0.889 | 0.971 | 0.066 |
| majority | 0.272 | 0.333 | 0.459 | 0.019 |

S+A+U minus S+A：ΔMacro-F1=0.131，按 App 分组的配对 bootstrap 95% 区间 [0.110, 0.153]。

S+A+U minus S+A+shuffled_U：ΔMacro-F1=0.131，按 App 分组的配对 bootstrap 95% 区间 [0.110, 0.152]。

### intervention

| 模态 | Macro-F1 | Balanced acc. | AUROC | ECE |
| --- | ---: | ---: | ---: | ---: |
| S | 0.851 | 0.871 | 0.977 | 0.033 |
| S+A | 0.868 | 0.881 | 0.977 | 0.064 |
| S+U | 0.975 | 0.976 | 0.998 | 0.121 |
| S+A+U | 0.971 | 0.974 | 0.998 | 0.126 |
| S+A+shuffled_U | 0.859 | 0.875 | 0.977 | 0.067 |
| majority | 0.219 | 0.333 | 0.461 | 0.001 |

S+A+U minus S+A：ΔMacro-F1=0.103，按 App 分组的配对 bootstrap 95% 区间 [0.087, 0.120]。

S+A+U minus S+A+shuffled_U：ΔMacro-F1=0.112，按 App 分组的配对 bootstrap 95% 区间 [0.093, 0.132]。

无需干预样本上的错误干预率：0.019。

## 科学结论边界

- H1：已测量公开图像基线；手机场景、连续行为与独立距离真值仍未验证。
- H2：仅完成合成标签机制验证；真实同步用户上的互补增益待检验。
- H3：仅完成启发式干预类别预测；真实干预有效性仍需受控用户实验。

完整指标、预测、分组清单和数据哈希见同目录 JSON/JSONL 文件。
