# 数据交换格式 temporal-pilot-v1 / pilot-window-v2

机器Schema位于 `schema/session.schema.json` 的 `$defs`。JSON Schema验证字段类型，Python校验器进一步验证坐标、时钟、因果截断、文件哈希和分组；单靠Schema不能证明物理同步或人类标注真实性。中文文本UTF-8，时间使用整数ns，像素为实际view坐标；勿将ns转成不够精确的浮点或JavaScript Number。

```text
session.json
session_events.jsonl
export_manifest.json
trials/<trial_id>/
  trial_meta.json
  front_camera.mp4       # 本版不生成，使用下面逐帧序列
  frames/*.jpg
  camera_frames.jsonl
  ui_states.jsonl
  touch_events.jsonl
  stimulus.png
  feedback.json
```

`session.json`：schema_version、匿名participant_id、全局session_id、evidence_tier、clock、created/stopped_ns、status、trial_ids、device、camera、presentation_seed、protocol_sha256。device保存型号/SDK/真实分辨率/Android display density；Android density不是独立测量PPI。camera保存前摄状态、sensor time source、orientation、镜像状态、实际记录方案。optional外部量具距离单独声明来源，不进Camera估计特征。

`trial_meta.json`：participant/session/trial身份、task、template_id、onset_ns、offset_ns、status、完整stimulus配置、outcome。outcome含success、completion_time_ms、misclicks、help_requests，与自评分开。Fixation的success未知；只能确认显示了指令目标，不能确认眼球实际凝视。暂停/停止中断标aborted，恢复为新attempt。

`camera_frames.jsonl`：frame_id、sensor_timestamp_ns、arrival_elapsed_ns、stored_elapsed_ns、mapped_timestamp_ns、clock_source、mapping_status、sync_uncertainty_ns、clock_mapping、rotation_degrees、width/height、status、path、sha256。status区分recorded / sampled_out / pre_onset / write_error，不能把采样略过直接算硬件丢帧。raw帧不镜像，离线按rotation_degrees转正。

REALTIME要求mapped==sensor，二者与elapsedRealtime同基准。UNKNOWN默认mapped可能null；arrival偏移估计未验证时sync_uncertainty是null，不能声称误差为0。独立映射需要`slope`、`offset_ns`、`max_error_ns`、`validated:true`、`validation_method:independent_capture_clock_pairs`，以及至少3个`{sensor_ns,reference_capture_elapsed_ns}`锚点。校验残差只能检验提供的锚点；锚点本身仍需真实独立来源。

`ui_states.jsonl`：timestamp_ns、timestamp_kind、view_size_px、view_origin_screen_px、page_id、target_element_id、render_valid、screenshot_path、elements。draw_callback_submission不是photon onset。每个element含element_id、自然text/text_lines、bounding_box_px、clickable_region_px、font_glyph_height_px（计划值）、actual_glyph_height_px（实测）、ink_bounding_boxes_px、role、visual_contrast、page_id、navigation_transition、render_timestamp_ns。bounding_box是按钮/目标显示框；实际文字墨迹框另存。Fixation还保存全屏像素instructed_target_screen_px。物理屏幕位置=局部坐标+view_origin。

`touch_events.jsonl`：timestamp_ns、raw_uptime_ms、event_clock_offset_ns、mapping_uncertainty_ns、action(down/up/cancel/help_request)、局部x/y、element_id和即时correct_target_hit。后者由当时已知任务目标及可点击区域判定，绝不由最终outcome补写。

`feedback.json`：status=provided/missing/not_applicable。provided需要timestamp_ns、label_source=self_report、difficulty_rating(1–5)、difficulty_type(visual/motor/navigation/semantic/none)、wants_help(bool)、preferred_assistance(zoom/highlight/explain/none)。mock只能使用mock_self_report_fixture来源，不能混入真实样本。反馈时间晚于trial offset，偏好不等于独立干预效果真值。

`export_manifest.json`逐文件保存相对path、bytes、SHA256（自身不哈希），导出ZIP包含全部原始文件。导入检查路径、重复ID、CRC/解码、尺寸和哈希。当前采集器和提取器使用JPEG帧序列，未实现MP4容器导入；其他系统的MP4须先转为逐帧图片并提供独立验证的capture映射，不能用播放PTS补系统时钟。

提取结果每个Session独立存于`reports/.../features/<session_id>/`：camera_features.jsonl、windows.jsonl、extraction.json。窗口版本pilot-window-v2，包含participant/session/trial/template、mode、input_start/end_ns、label_time_ns、label_resolution=trial_only、screen/actions/user和六步sequence。相机特征只保存观测/估计，不写difficulty标签；trial自评只关联窗口级监督。

窗口特征表采用显式白名单，见 `pilot_features.py` 的SCREEN_KEYS / ACTION_KEYS / USER_KEYS。face_scale是归一化脸宽，relative_inverse_scale_change=首个已见有效scale/当前scale−1。head rotation/velocity使用真实ns间隔，>0.5s缺口不计算连续角速度。feature_stability是姿态Euler序列展开后的平均标准差（rad），不是“困难真值”。gaze占比仅在可靠gaze_region及confidence≥0.8时计算；本轮后端没有经过验证的屏幕gaze，故为空。
