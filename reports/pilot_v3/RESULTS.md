# Mobile Pilot v3 — 实际结果

已先只读分析10月30日原件，再生成设计、完成同源压缩/特征准备，最后构建并安装v3。没有重新下载研究数据/模型，没有训练MPIIFaceGaze、GRPO、完整GUI Agent或大Video Transformer。

## P0：真实Session质量结论

原件 `test1030_20261030_144219`：H.264 [720, 1280]，182.777s，258.78MB / 246.79MiB，实际11.33Mbps。5173帧逐项PTS与记录一致、0重复、0个>75ms缺口。局部约27/30FPS，不能称固定30FPS。

| 区间 | 估计时长(s) | 区间内实际PTS帧率 |
|---|---:|---:|
|feedback|102.28|27.97|
|fixation|7.43|29.89|
|instruction|4.01|29.89|
|quality_or_startup|18.32|29.91|
|visual_search|50.74|28.03|
|assistance_subset|17.92|27.44|

assistance_subset与任务区间重叠；上述时段归因依赖未验证映射，不是物理同步结果。具体每trial的FPS/字节/标签见[trial_quality.csv](audit_20261030/trial_quality.csv)，完整审计见[session_audit.md](audit_20261030/session_audit.md)。

ImageAnalysis=7.27FPS，Live推理结果=2.09FPS，成功face=2.06FPS；这些不是录像FPS。Live face成功98.69%，双眼入框代理97.64%，strict完整面部代理仅3.14%。14个trial均有face代理，但13个没有strict full-face有效Live结果。

离线同一MP4的117帧QC样本（96个系统样本+分层补充）：face=97.44%，双眼入框代理=87.18%，完整面部代理=25.64%。分层补充使这些比率不能直接代表全视频发生率；纯96样本结果另列offline_face_summary.json。抽样、分辨率/裁剪不同，不能把Live与离线比率差当模型准确度或压缩损失；新APK补记录Analysis实际尺寸/cropRect/rotation，但未验证共同视野。脸边缘截断/横移失败和完整样本均已私有目视检查；没有将代理叫gaze/精确距离/头姿真值。

9个搜索试次全部重复“检查预约”。仅font pair的元素变化为字形大小，但重复暴露、已知答案、目标位置、顺序和帮助均影响表现，不能从后续速度因果归因。没有求助的6个trial中5个自评≥3，不能将无help标成无困难。自评/原因/helpfulness保留，不当逐帧真值。[目标分布](audit_20261030/target_distribution.csv) · [帮助复核](audit_20261030/assistance_summary.csv)。

Touch坐标、uptime映射、所有PNG完整性及帮助后的UI对应关系已核对。旧v2缺显式assigned/self-selected来源，只能按时间推断，不能当随机干预有效性证据。

**物理时间同步仍unverified，全部14个原试次不用于“已验证对齐”的严格融合指标。** 无独立曝光/编码PTS锚点；回调offset spread和最近帧残差不是物理误差。设计了带光电观测、USB时间区间及留出边沿的光学校准方案，尚未执行。[timing_audit.md](audit_20261030/timing_audit.md) · [校准方案](audit_20261030/synchronization_protocol.md)。

## P1：新任务与平衡设计

R=6选项文字辨认；S=24选项、易读字体的服务查找；M=24选项、较小字体的组合负荷。初始2×2仅操控glyph size与choice count；font weight、区域背景和核心slot保留，其他潜在因素逐项记录而不同时随机改变8项。任务族不是独立困难真值，区分性仍需反馈验证。

Full24/Quick8个目标均不重复，每cell与每屏幕2×2区域分别6/2项；未来Session目标不出现在别页干扰项。16组轮换每个目标的4条件×4区域，Williams顺序平衡；普通干扰项仍会重复，仍需考虑熟悉化。任务前随机模式与任务中自选模式分开，额外求助标rescue_crossover。随机化块randomization_block_id与语义/文字长度匹配族pair_id分开；单个匹配族可能只有一个目标，不能强行一对一比较。原始assigned不改写；后续分析须预先规定如何处理crossover，不按结果挑选。

[变量表](design/stimulus_factorial_design.csv) · [词库](design/target_vocabulary.json) · [平衡报告](design/condition_balance_report.md) · [任务定义](design/task_taxonomy.md)。

实际Android截图（明确无相机测试）：[R](design/android/readability_example.png) · [S](design/android/visual_search_example.png) · [M](design/android/mixed_example.png)。同目录外的 *_example.png 是PIL参考渲染，未冒充Android实测。

## P2：存储与质量权衡

原视频占258.78MB；其中Feedback约102.28s、141.97MB payload。真正Fixation+Search约58.17s；高码率+非任务全程录制解释了接近/超过200MB的体积。[完整体积分解](audit_20261030/storage_breakdown.md)。

| 配置 | MiB | 实际Mbps | 同帧face检出率 | 条件pose代理差均值(deg) |
|---|---:|---:|---:|---:|
|original|246.79|11.33|0.974|0.000|
|h264_720w_1mbps|21.93|1.01|0.974|0.395|
|h264_720w_2mbps|43.81|2.01|0.974|0.366|
|h264_720w_4mbps|87.56|4.02|0.974|0.356|
|h264_480w_1mbps|21.92|1.01|0.974|0.494|
|h264_480w_2mbps|43.81|2.01|0.974|0.382|
|h264_480w_4mbps|87.57|4.02|0.974|0.338|

全部6份派生版本保留原5173个PTS，没有覆盖原片。Face统计包含117帧所有失败；pose/landmark差只在双方有效时定义，并报告n及缺失。检测率相近不证明瞳孔/眼睑保真；眼部ROI PSNR、稀疏变化率差和私有目视对照见[压缩报告](compression/compression_report.md)。条件pose差是同一模型一致性，不是真值准确度。

calibration保留原件；normal可进一步验证720p2/4Mbps，debug可试480p1/2Mbps。它们目前是桌面派生实验，不是设备CameraX码率模式已验证。未把候选码率写死为设备必达值。长问卷/休息暂停录像可省空间，但需显式记录缺口，并承认会失去跨任务状态连续性。当前APK未新增这三档录制/自动分段开关。

## 时序训练准备

已生成39个2/3/5秒近期窗口、39段实际采样短片（合计7.34MB），单帧灰度人脸表示39×256，显式缺失mask的合并cache 12,976 bytes。短片的每个PTS逐项匹配源帧，未插值伪造观察；原件仍保留。[准备说明](temporal/README.md) · [缓存成本](temporal/cache_module_recheck/cache_cost.json)。

Live通道用capture+available_ns严格截止；视频/appearance截止仅基于估计映射，不能声称物理上已保证pre-event。固定2秒前缀、近期2秒仅6个可用trial（3后续求助、3未求助）；更短试次被排除会有选择偏差。当前单人单Session、同步未验证，模型训练被阻止，没有融合accuracy/F1，也没有elderly或跨用户泛化结论。Screen-only / Screen+Touch / +User temporal是准备接口，未伪称完成真实对照训练。 新增 `pilot-v3-evaluate` 小模型入口，实际运行后按检查条件停止：[评估检查结果](temporal/evaluation/results.json)。2秒前缀的6个trial自评困难标签全为1；后续求助的3/3划分是另一目标，不能替代困难标签。Logistic / HistGradientBoosting / GRU未来训练路径尚未在合格数据上运行，当前没有模型性能结果。

## P3/P4：APK与实际验证

APK：`mobile_pilot/app/build/outputs/apk/debug/app-debug.apk`，60,123,846 bytes。SHA256：`c86a60d3ce48ee30d4ad9d618cc69982f9b938d8c60a226c930e2f700e510a0f`。已安装nova12，设备包hash一致。[最终构建日志](build/build_final.log) · [最终指纹与短测](build/final_verification.json) · [双模式完整试跑及兼容证明](build/core_test_verification.json)。

Python：108 passed in 4.78s；JVM：15项通过。v1 JPEG、v2真实MP4与v3无相机两份导出均通过读取/CRC/hash/schema/UI检查；旧Session未迁移。APK无INTERNET/麦克风权限。

两个新测试分别为requested_only/group0与assigned_pre_task/group1，每个8个唯一目标、覆盖R/S/M；随机帮助在UI0已呈现，source明确区分assigned/self_selected/rescue_crossover，onset精确对应记录的UI draw事件（仍非photon时间）。区域提示与oracle目标提示分开，单候选区域另标oracle-equivalent。
- device_smoke_v3_requested_20261031_100924: requested_only, source={'self_selected': 2}, status={'completed': 7, 'timeout': 1}, misclicks=1。
- device_smoke_v3_assigned_20261031_100924: assigned_pre_task, source={'assigned_pre_task': 8, 'rescue_crossover': 1}, status={'completed': 8}, misclicks=0。

完整两模式试跑的包为0.4.0，指纹与逐trial结果保存在core_test_verification.json。最终0.4.1只修正匹配元数据、帮助有效性标签和问卷退出；384个任务UI模板、顺序及帮助分配未改变，另完成无相机元数据短测和反馈界面短测，没有把旧全套试跑伪称为最终包重新跑过。

最终标签为self-report-v3.1：实际有帮助必须主动选择1–5或“无法评价”，没帮助时为不适用/null，未提交保持missing，拒绝默认0分。技术测试若填写值会标device_test_fixture；本轮最终短测未输入主观答案。[标签界面检查](build/feedback_check.json) · [匹配修订](design/matching_revision.json)。旧数据不改，未来须同时按protocol_version、label_schema_version、evidence_tier分组。

以上为ADB功能验证，无相机、无新视频、主观评分保持missing，不当真人困难研究。没有重新测v3的视频FPS、分析视野、码率三档或物理同步。P0的录像质量结论只属于原始v2真实Session。

## 错误记录与保留

- 首次PTS审计用float截断导致5个1µs假差；改精确Fraction转换后完全匹配，未改标签。失败目录保留。
- 首次编译有UI变量作用域错误，已修正并保留build_attempt_syntax.log。
- 无相机自动测试读取历史UI状态，产生误触/超时；修正定位器并保留原试次，不把失败重写成功。
- 导出测试开始默认选中旧Session，后改为显式选中并核对文件名。早期拉取快照含0字节/未写完文件；仅CRC完成且文件hash通过的ZIP计成功，快照留private。
- 测试中已有matriöx函数拼写造成NameError；保留副本后只修正拼写为matrix。VIDEO_V2.md的既有用户编辑未动。

本轮开始时392个原始Session/历史报告文件hash未变；设备原Session manifest和原视频指纹也未变。所有面部图片、逐帧生物特征、派生视频/短片与设备导出留在data/private，gitignore保护；没有上传。

尚未完成：独立光学物理同步实验；新任务区分性的真实反馈验证；多参与者/跨用户评估；眼动/距离/头姿真值验证；设备三档码率与自动暂停策略；新v3视频记录实测；大型视频模型/GUI Agent/GRPO（本轮明确不做）。

完整可复制命令：[mobile_pilot/VIDEO_V3.md](../../mobile_pilot/VIDEO_V3.md)。实际执行记录：[commands_executed.json](commands_executed.json)。

Face/Head逐帧轨迹与目视检查图均保存在private目录；普通figures只放FPS和目标位置。当前采样clip与特征是训练准备，不是未验证同步情况下的模型成绩。
