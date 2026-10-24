- 做一个app list表：App-feature list generation
- 翻译老人的指令到语音助手
- 理解老人的指令，具体执行操作

康春工作在语音，我要在这基础上做图像相关

benchmark:

$$
\text{physical user state}
+
\text{screen state}
+
\text{interaction history}
\rightarrow
\text{difficulty}
\rightarrow
\text{adaptation}
$$

- ElderBench 看用户“说了什么”（更偏向于验证康春工作必要性）；你看用户“正在经历什么”
- UI-Hawk看历史 screen stream：UI grounding，UI referring，screen QA，screen summarization。最后会把上面的内容总结成历史流，比如把用户点击屏幕上的具体位置，翻译成具体点了什么内容，是进行了哪些屏幕操作

所以我做：
$P(d_t|S_{1:t},U_{1:t},A_{1:t})$

- $S$：screen history . $U$ ：user-facing camera history . $A$ ：touch/action history

结构：什么时候做融合好？touch/action history是在Screen stream里面？
Screen stream
      ↓
Visual Encoder
      ↓
      ├────────┐
               ↓
         Multimodal Fusion
               ↑
      ├────────┘
      ↓
User-camera stream
(face / eye / pose)

输出：
difficulty type
+
confidence
+
adaptive action

真正值得研究的是 User–UI Alignment / Cross Attention。
用户的这个行为，到底与屏幕上的哪个 UI element 有关系？

$$
\boxed{
Z^{U\leftarrow S}
=
\operatorname{softmax}
\left(
\frac{QK^\top}{\sqrt d}
\right)V
}
$$

### Contribution 1 — Dataset + Benchmark

- We introduce a synchronized user–GUI interaction dataset capturing user-facing camera streams, screen streams, and touch trajectories during controlled and real-world mobile tasks, enabling systematic evaluation of user difficulty understanding and adaptive mobile interaction.

#### Contribution 2 — User-Adaptive Agent

- We propose a User–UI multimodal model that jointly reasons over user state, screen history, and interaction trajectories to detect user difficulty and determine when and how the mobile interface should adapt.

### Dataset + Benchmark + supervised model 做通之后，再进入 Personalized GUI Agent

Controlled Difficulty 给他真正的视觉任务。

例如： 请找到“医保支付” -> 屏幕上找 -> 改变UI。一定采连续时间序列
Difficulty 的定义
这里应该让老人自己描述任务，而不是研究人员替他们写标准 instruction

先：

$$
\boxed{
\text{Behavior}
+
\text{User Camera}
+
\text{GUI}
\rightarrow
\text{Difficulty Understanding}
}
$$

后：

$$
\boxed{
\text{Intent}
+
\text{Difficulty}
+
\text{GUI State}
\rightarrow
\text{Adaptive Mobile Agent}
}
$$

证明“用户困难确实能从 front camera + interaction dynamics 中被可靠观测，而且加入 user stream 显著优于 screen-only”，这项工作的核心 premise 就站住了


| 工作                                                         | 已经解决什么                               | 你继承什么                    | 你的延伸                                                       |
| ------------------------------------------------------------ | ------------------------------------------ | ----------------------------- | -------------------------------------------------------------- |
| **GazeCapture / Eye Tracking for Everyone, CVPR 2016** | 手机前置摄像头估计 gaze                    | face/eye/mobile gaze protocol | gaze 不作为最终目标，而作为 user-state signal                  |
| **COAS2W, EMNLP 2025**                                 | 中国老年人口语理解                         | 中国老年用户、真实用户差异    | 从“理解用户说什么”扩展到“理解用户遇到什么困难”             |
| **UI-Hawk, EMNLP 2025**                                | screen-stream understanding                | 历史 GUI 状态建模             | 增加同步 user-camera stream                                    |
| **ElderBench, 2026**                                   | 249 个老年人真实任务、20 Apps              | elderly mobile benchmark 范式 | 从 linguistic difficulty 扩展到 physical/user-state difficulty |
| **OpenPhone**                                          | 小模型 Mobile Agent + SFT→GRPO + 端云协同 | 后训练框架                    | reward 加入 user effort / intervention                         |
| Driver Monitoring / gaze estimation                          | head/eye/body/attention                    | user sensing baseline         | 从驾驶 attention 转成 mobile interaction difficulty            |

