# Temporal Mobile Pilot 操作与分析协议

本协议扩展旧 `docs/PILOT_PROTOCOL.md`。先进行用户自主设备自测，验证采集完整性；本文不启动招募、用户实验或界面干预。

## 分开检验

H1需要实际手机前摄的检测/头姿/relative scale可靠性。Fixation只记录instructed targets；gaze角度/屏幕准确率还需要可靠校准与独立参考。单目尺度无法独立给出绝对eye–screen距离。头姿accuracy需独立姿态参考，不能用MPII官方估计pose当手机真值。

H2比较相同Trial/预测时间/Split下的S、S+A、U、S+U、S+A+U，以及过去trial错位User对照。主要监督是任务后主动self-report rating≥3；困难类型保留用于后续区分视觉、运动、语义等。主要二分类不是“纯视觉困难”的独立分类器，需足够各类真实数据后另设分析。

H3本轮只记录帮助需求/偏好，不实施帮助，不评价干预收益。未来需独立设计适当干预与不必要干预代价；本轮不能声称H3得到验证。

## 采集顺序

先在自己的设备确认屏幕坐标、字形、触摸、方向和权限拒绝路径。创建新匿名Session，保存设备/有效随机种子/协议SHA。先25点×2轮注视，再48个视觉搜索trial；需要时暂停，不要求用单次长Session凑样本。独立量具距离可留空，不能填写由脸大小反推的值充当真值。

注视每点计划1500ms；报告实际onset–offset与camera覆盖，不把服从指令当作独立眼动测量。视觉搜索随机化呈现，目标/干扰项均为自然中文服务文本。字体、按钮、元素数、偏心度、对比度、语义相似度、信息密度、左右位置采用48-run平衡主效应设计。展示条件是操纵变量，绝不直接作为参与者困难标签。

搜索结束主动回答四项：困难1–5分、主要困难类型、想获得帮助与否、希望的帮助类型。成功/时间/误点/主动help按钮记录独立保存。困难评分与失败不强制一致，不事后用公式“纠正”自评。

完成后Stop，再导出ZIP。检查帧/截图/JSON哈希，抽查一个trial的实际图像与触摸位置、摄像头旋转、传感器时钟源、采样FPS、中断与缺失。UNKNOWN源如果只有arrival估计，报告同步未验证；不要强行与UI相减后训练融合模型。Session中断或损坏时保留原包及错误日志，不能补造数据。

## 预先固定分析

trial-level预测在任务offset时使用完整已见历史。online replay分别固定1、2、3秒prefix，仅使用当时capture且已available的帧、已发生动作和UI状态。未持续到prefix的任务作为不符合窗口条件单独报告；不能将这些容易/快任务悄悄删除后宣称适用于所有trial。

自评是trial-resolved监督，无法定位困难何时发生。六个累计特征步骤只是GRU输入，不是六个独立困难标签。不可随机切分同一trial的窗口。单人只做session-disjoint feasibility；多人才可做participant-disjoint。至少3个独立组才能保持训练/验证/测试分开；重复UI模板跨组时purge，没有足够数据就不报模型性能。

Logistic/HGB内部验证选择超参；GRU小型、固定架构、验证early stopping。插补/缩放仅拟合训练组。M5只用同partition、同Session中过去trial的User prefix；首trial缺失导致缺失率与M4不同，不能单凭该对照宣称因果作用。报告AUROC、Macro-F1、balanced accuracy、Brier/ECE、逐组表现、Camera缺失和不可评估原因；小样本不声称显著性。

## 必须真机确认的项目

JDK/SDK下编译和JUnit；首次/拒绝/撤销Camera权限；无前摄；图像色彩和rotation；实际像素/ink与点击框；App转后台/锁屏/Pause恢复；存储写失败；UNKNOWN映射；Stop后导出/重新导入；删除单Session；real标签与mock完全隔离。当前本机Python测试覆盖数据合同和泄漏，不替代这些设备检查。

有效闭环之后再考虑可选Motor Precision与多步导航。未开始GUI Agent、GRPO、复杂多模态模型或真实干预实验。
