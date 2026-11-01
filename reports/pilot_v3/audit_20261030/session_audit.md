# 2026-10-30 real Session audit

Session `test1030_20261030_144219`；manifest 122文件hash通过、所有30张PNG解码通过。原始文件只读。

录像 182.777s / 258.78MB，h264 [720, 1280]；整体 28.30FPS；瞬时FPS {'n': 5172, 'mean': 28.381147737355803, 'p05': 26.913553665626008, 'median': 26.986911347996223, 'p95': 29.900729577801698, 'max': 37.29812390436761}；>75ms缺口 0，重复PTS 0。阶段/逐trial见CSV与video_stats，不能用全程均值替代。

ImageAnalysis 7.27FPS；Live推理结果 2.09FPS；成功face结果 2.06FPS。Live face成功率 98.691%；双眼in-frame代理 97.644%；strict完整面部代理 3.141%。

离线117帧复核：{'n': 117, 'face_ratio': 0.9743589743589743, 'strict_full_face_proxy_ratio': 0.2564102564102564, 'edge_truncation_proxy_ratio': 0.6581196581196581, 'eyes_in_frame_proxy_ratio': 0.8717948717948718, 'bbox_area': {'n': 114, 'mean': 0.5659188523456042, 'p05': 0.3746886142953601, 'median': 0.5660162523624193, 'p95': 0.7182285702093407, 'max': 0.8432347597681096}, 'bbox_edge_margin': {'n': 114, 'mean': -0.051767331727764064, 'p05': -0.32689422369003296, 'median': -0.027196824550628662, 'p95': 0.10471699461340901, 'max': 0.16551387310028076}, 'missing_full_face_success_stratum': False, 'private_manual_review': 'reports/pilot_v3/private/audit_20261030/face_contact_sheet.jpg'}。人脸图与逐帧生物特征只保存private目录；公开报告不包含脸像。head pose/scale/blink均为模型代理，非gaze/距离/头姿真值。

目标重复：{'检查预约': 9}；无有效face特征trial 0/14；全部14个trial因缺独立时间锚点不用于严格验证的融合性能。

Touch坐标/时钟一致性：True；帮助交付后对应UI均存在：True。v2未显式记录assigned/requested的研究模式来源，按时间推断只能描述，不能当随机干预因果效果。

9个搜索trial均为同一目标“检查预约”；第一次求助后已暴露目标，后续速度存在记忆、位置、帮助、顺序和条件共同影响，不能把速度变化归因于字体/帮助单因素。font pair的元素变化字段见pair_audit。

自评均保留原始值；没有求助不代表没有困难。Helpfulness=0必须结合是否实际有帮助，不应当作零帮助收益。单人、重复目标、未验证同步：仅within-person feasibility，不能推断老年人总体或跨用户可靠性。

困难标签逐trial保存在trial_quality.csv，Fixation无自评分并且不是眼动真值；反馈是trial-level自报，不是逐帧困难起点。

存储主要来自高码率全程录像；反馈/指导的估计时长和字节见storage_breakdown.md。应保留校准/交互段，长休息/反馈可选暂停，但必须显式记录视频缺口，不插值伪造观察。

## 分层随机图像复核

已按seed=20261030从face成功/失败及full-face成功/失败层抽取并查看本地私有联系表。可见部分画面下颏/脸缘贴近或超出画面边界；横向侧移的少数帧检测失败，同时也有较完整样本。模型的每个边界判定未被独立逐帧人工标注，不将此抽样查看冒充量化人工真值。

Live strict full-face=3.14%，离线MP4样本=25.64%；二者采样频率、输入尺寸/纵横比及可能的裁剪不同（源码Analysis请求640×480，录像720×1280），不能将比率差当压缩损失或模型准确度差。旧记录缺少完整analysis cropRect/width/height元数据，具体差异原因仍未解决；新版本应记录实际分析帧几何信息。私有联系表位置见manual_review_index.json，不上传面部图片。

PTS对比最初发现5个1µs差异，已确认是审计代码的浮点截断：用精确Fraction×1000000转换后5173帧与官方保存PTS逐项完全一致。没有修改原始PTS；失败分析目录保留。

Camera有效性口径：所有14个trial均有至少一次Live face代理；但其中13个trial没有任何strict full-face有效Live结果。两者不能统称“校准合格”。Face quality CSV补充稀疏离线bbox位置、面积和截断率，并保留各trial离线样本数。

离线117帧包含96个系统间隔样本及分层补充失败/成功样本。117帧比率仅作QC样本描述，不是无偏全视频发生率；纯96样本结果另列offline_face_summary.json。

逐帧头姿/face-scale轨迹图随逐帧数据保存在private/audit_20261030/face_and_recording_trajectories.png；普通figures目录仅包含编码FPS与目标位置图，不含人脸像。私有内容不会自动上传。
