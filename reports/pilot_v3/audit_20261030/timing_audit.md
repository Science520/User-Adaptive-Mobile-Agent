# Timing audit

MP4逐帧PTS与保存的encoded_frame一致。Recorder事件：Counter({'start': 1, 'finalize': 1})。Status callback-derived offset spread=296.588ms，包含调度/编码延迟，不是同步误差。

没有独立曝光/PTS锚点，全部14个trial不能进入“已验证对齐”的严格融合评估。Nearest frame residual仅为估计覆盖，物理uncertainty=null。

可重复校准方案：将可见外部LED放在前摄画面角落，由微控制器输出伪随机光码并通过有线USB记录触发序列；Android用elapsedRealtime记录USB接收上下界，硬件独立记录发光触发。以MP4像素亮度检测每次LED跃迁，拟合PTS→elapsed的分段仿射映射；至少30个边沿、覆盖开始/结束及Pause/Resume，保留外部硬件延迟/USB调度区间、留出边沿误差和漂移。仅使用屏幕requestDraw或用户反应时都不是光子真值。若仅本机屏幕反射伪随机亮度，则只得到包含显示延迟的可重复估计，不能标validated。
