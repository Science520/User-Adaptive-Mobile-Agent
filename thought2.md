
“GUI Agent 不仅理解手机屏幕，还理解正在使用手机的人”。

# 项目暂定：User-Adaptive Mobile Agent

### 核心研究问题

现有 Mobile GUI Agent 基本遵循：

$$
\text{Screen}_t+\text{Instruction}+\text{History}_{1:t}
\rightarrow
\text{Action}_t
$$

UI-Hawk 已经进一步证明，仅看当前 screenshot 不够，需要建模历史 screen stream。:chatgpt-content-reference{index="0"}

我的核心扩展是：

$$
\boxed{
\text{Screen}_{1:t}
+
\text{Interaction}_{1:t}
+
\text{User}_{1:t}
\rightarrow
\text{User Difficulty}_t
\rightarrow
\text{Adaptive Action}_t
}
$$

其中最关键的新变量是：

$$
\boxed{\text{User State}}
$$

即 Agent 不仅问：

> **手机现在是什么状态？**

还要问：

> **用户现在是什么状态？他是不是看不清、找不到、理解不了、点不中？我是否应该干预？**

最终目标是：

> **Adaptive Mobile Intelligence in China's Super-App Ecosystem**

---

# 1. 现有工作与我的延伸关系

literature map：

| 工作                                                         | 已经解决什么                               | 你继承什么                    | 你的延伸                                                       |
| ------------------------------------------------------------ | ------------------------------------------ | ----------------------------- | -------------------------------------------------------------- |
| **GazeCapture / Eye Tracking for Everyone, CVPR 2016** | 手机前置摄像头估计 gaze                    | face/eye/mobile gaze protocol | gaze 不作为最终目标，而作为 user-state signal                  |
| **COAS2W, EMNLP 2025**                                 | 中国老年人口语理解                         | 中国老年用户、真实用户差异    | 从“理解用户说什么”扩展到“理解用户遇到什么困难”             |
| **UI-Hawk, EMNLP 2025**                                | screen-stream understanding                | 历史 GUI 状态建模             | 增加同步 user-camera stream                                    |
| **ElderBench, 2026**                                   | 249 个老年人真实任务、20 Apps              | elderly mobile benchmark 范式 | 从 linguistic difficulty 扩展到 physical/user-state difficulty |
| **OpenPhone**                                          | 小模型 Mobile Agent + SFT→GRPO + 端云协同 | 后训练框架                    | reward 加入 user effort / intervention                         |
| Driver Monitoring / gaze estimation                          | head/eye/body/attention                    | user sensing baseline         | 从驾驶 attention 转成 mobile interaction difficulty            |

其中 GazeCapture 是非常重要的直接参考：其官方项目就是 CVPR 2016 *Eye Tracking for Everyone*，使用普通移动设备进行 eye tracking。

康春的 **COAS2W** 则提供了非常好的“怎么从中国老年用户问题构建 dataset → benchmark → model”的范式：10,004 条老年人口语，包含书面化版本、细粒度错误标签和四句上下文，而且证明 context 对模型有效。:chatgpt-content-reference{index="2"}

而最新的 ElderBench 已经收集了 **249 个自然产生的老年人 smartphone tasks，覆盖 20 个 App**，重点发现 indirect speech、referential ambiguity、under-specification 会显著影响 GUI Agent。

因此不要重复做：

> 老年人 + 手机任务 → GUI Agent 成功率。

我的 gap 应该是：

> **Existing elderly-agent benchmarks model what the user says; we model what the user is experiencing.**

---

# 2. 整个项目分三阶段采数据

我不建议一上来就找老人操作微信。

应该从**高度可控 → 半可控 → 真实世界**逐层建立。

## Dataset I：User–Phone Geometry Calibration

这是我先前提出的“64 格”实验。

目的不是论文最终任务，而是建立：

$$
\text{front camera}
\rightarrow
\text{eye/head/phone geometry}
$$

### 实验装置

手机屏幕划分成：

$$
8\times8=64
$$

个区域。

但不要真的画出 64 个格子让用户选，而是随机在某个区域中心出现 fixation target：

```text
┌─────────────────────┐
│    ·                │
│                     │
│              ●      │
│                     │
│                     │
│       ·             │
│                     │
└─────────────────────┘
```

● 出现在哪里，就是已知 ground-truth gaze target。

例如屏幕宽高：

$$
W\times H
$$

第 $(i,j)$ 个 grid center：

$$
x_{ij}=\frac{i+0.5}{8}W
$$

$$
y_{ij}=\frac{j+0.5}{8}H
$$

其中：

$$
i,j\in\{0,\ldots,7\}
$$

这样每张 front-camera frame 都自动获得：

$$
(x_{\text{gaze}},y_{\text{gaze}})
$$

标签。

---

# 3. 不要只固定一个 $x$ cm

这是我原始方案一个需要修改的地方。

应该主动改变：

### Distance

例如：

$$
d\in\{25,35,45,55\}\text{ cm}
$$

### Phone pitch

$$
\alpha\in\{-30^\circ,-15^\circ,0^\circ,15^\circ,30^\circ\}
$$

### Phone yaw

$$
\beta\in\{-30^\circ,-15^\circ,0^\circ,15^\circ,30^\circ\}
$$

### Font / target size

例如：

$$
s\in\{12,16,20,24,32\}
$$

不要把这些变量当成“干扰项”。

**它们就是数据。**

因为现实世界里的困难可能表现为：

$$
\text{看不清}
\rightarrow
\text{改变手机距离}
\rightarrow
\text{改变头部姿态}
\rightarrow
\text{眯眼}
\rightarrow
\text{凝视时间增加}
$$

这些 temporal changes 恰恰是 difficulty signal。

---

# 4. 几何模型怎么建立

简化原来的：

> 手机 → 手 → 身体 → 脖子 → 头 → 眼睛

因为没有必要显式建完整人体运动链。

定义 **phone coordinate system**：

手机中心：

$$
O_p=(0,0,0)
$$

手机屏幕法向：

$$
\mathbf n_p
$$

左右眼三维位置：

$$
E_L,E_R
$$

眼睛中心：

$$
E=\frac{E_L+E_R}{2}
$$

那么用户—手机距离就是：

$$
\boxed{
d=\|E-O_p\|_2
}
$$

---

## Viewing angle

手机到眼睛的方向：

$$
\mathbf v=
\frac{E-O_p}
{\|E-O_p\|}
$$

则 viewing angle：

$$
\boxed{
\theta=
\cos^{-1}
\left(
\frac{
\mathbf n_p^\top(E-O_p)
}{
\|E-O_p\|
}
\right)
}
$$

理想正视：

$$
\theta\approx0
$$

手机越倾斜：

$$
\theta\uparrow
$$

---

# 5. Gaze 与 Screen Coordinate

进一步估计眼睛 gaze direction：

$$
\mathbf g
$$

眼睛出发的 gaze ray：

$$
R(\lambda)=E+\lambda\mathbf g
$$

手机屏幕可以表示成平面：

$$
\mathbf n_p^\top(X-O_p)=0
$$

令 gaze ray 与屏幕相交：

$$
\mathbf n_p^\top
(E+\lambda\mathbf g-O_p)=0
$$

得到：

$$
\boxed{
\lambda=
\frac{
\mathbf n_p^\top(O_p-E)
}{
\mathbf n_p^\top\mathbf g
}
}
$$

因此 gaze intersection：

$$
\boxed{
G=
E+
\frac{
\mathbf n_p^\top(O_p-E)
}{
\mathbf n_p^\top\mathbf g
}
\mathbf g
}
$$

再通过 camera calibration / homography：

$$
G\rightarrow(x_g,y_g)
$$

得到：

> 用户正在看屏幕哪里。

这是 Dataset I 最基础的任务。

---

# 6. Dataset II 作为关键创新：Controlled Difficulty

然后不要继续让用户“看点”。

开始给他真正的视觉任务。

例如：

> 请找到“医保支付”。

屏幕上展示：

```text
医疗健康    出行
医保支付    生活缴费
扫一扫      我的账单
```

然后系统性改变 UI。

### Manipulation variables

字体大小：

$$
s_{\text{font}}
$$

目标尺寸：

$$
s_{\text{target}}
$$

UI density：

$$
\rho_{\text{UI}}
=
\frac{\text{number of interactive elements}}
{\text{screen area}}
$$

contrast：

$$
C
$$

target eccentricity：

$$
e=
\sqrt{
(x_t-x_c)^2+(y_t-y_c)^2
}
$$

这些变量都可以自动控制。

---

# 7. 不要只采“图片”，一定采连续时间序列

这是另一个非常重要的修改。

最终数据不能是：

$$
\text{face.jpg}+\text{screen.jpg}
$$

而应该是：

$$
\boxed{
D_t=
(
U_t,S_t,A_t,Y_t
)
}
$$

其中：

### User stream

$$
U_t=
(
I_t^{face},
E_t,
H_t,
G_t,
d_t
)
$$

包含：

- front-camera frame
- eye landmarks
- head pose
- gaze
- phone-eye distance

### Screen stream

$$
S_t=
(
I_t^{screen},
UI_t
)
$$

包含：

- screenshot
- UI hierarchy
- font
- bounding boxes
- element semantics

### Action stream

$$
A_t=
(
touch_t,
scroll_t,
back_t,
zoom_t
)
$$

### Label

$$
Y_t=
(
difficulty_t,
type_t
)
$$

---

# 8. Difficulty 应该怎么定义？

这是整个 dataset 最重要的 annotation schema。

不要只做：

$$
\text{difficulty}\in\{0,1\}
$$

至少定义：

$$
D_t\in
\{
\text{None},
\text{Visual},
\text{Motor},
\text{Navigation},
\text{Semantic},
\text{Cognitive overload}
\}
$$

例如：

### Visual difficulty

看不清：

- 靠近/远离手机
- squint
- fixation 变长
- zoom

### Motor difficulty

知道按钮在哪，但是：

- 多次 misclick
- click offset 大
- 手部抖动

### Navigation difficulty

不知道下一步在哪：

- repeated back
- screen switching
- searching

### Semantic difficulty

看到按钮但是不知道是什么意思。

### Cognitive overload

信息过多：

- fixation 分散
- search path 长
- hesitation 增加

---

# 9. 可以构造一个 Difficulty Score

例如：

$$
D_t=
w_1z(T_{\text{fix}})
+w_2z(N_{\text{misclick}})
+w_3z(T_{\text{hesitation}})
+w_4z(N_{\text{back}})
+w_5z(\Delta d)
+w_6z(H_{\text{gaze}})
$$

其中 gaze entropy：

$$
H_{\text{gaze}}
=
-\sum_i p_i\log p_i
$$

表示 gaze 是否在大量 UI 区域间游移。

不过这里不要直接宣布这个就是“真实困难”。

更严谨的是把：

- 行为指标
- self-report
- task outcome
- annotator label

联合起来构建 ground truth。

---

# 10. Dataset III：China Real-world Mobile Interaction

最后才进入真正应用场景。

这部分可以和康春现有老年人研究资源结合。

任务不要为了“中国特色”硬造，而应该来自真实用户访谈。

例如：

| Domain    | 任务                       |
| --------- | -------------------------- |
| 微信      | 找公众号、发送文件、小程序 |
| 医疗      | 医院挂号、查看报告         |
| 支付宝    | 医保码、缴费               |
| 美团      | 找店、团购、核销           |
| 高德/滴滴 | 找地点、叫车               |
| 淘宝      | 找商品、理解最终价格       |
| QR        | 扫码点餐/服务              |
| 小程序    | 跨页面完成服务             |

ElderBench 已经说明自然老年用户指令与标准 benchmark instruction 存在明显差异，所以这里应该**让老人自己描述任务**，而不是研究人员替他们写标准 instruction。

---

# 11. 最终一个 trajectory 长什么样？

一次任务：

$$
\tau_i=
\{
(U_1,S_1,A_1),
\ldots,
(U_T,S_T,A_T)
\}
$$

再附加：

$$
Y_i=
(
success,
time,
errors,
difficulty,
intervention,
user\ rating
)
$$

于是可获得一个现有 GUI benchmark 非常少见的数据：

```text
USER                    PHONE

face video              screen video
eye                     UI hierarchy
head pose               UI elements
gaze                    touch
distance                scroll
     ↘                  ↙
       synchronized
            ↓
      task trajectory
            ↓
       difficulty
            ↓
      intervention
```

UI-Hawk 已经证明 screen history 对 GUI understanding 很重要；我的关键假设则是：

> **screen history + user history > screen history alone**

这就成为一个非常漂亮、可检验的 scientific hypothesis。

---

# 12. Benchmark 不要只设计一个任务

我建议最终 benchmark 有四层。

### Task 1 — User Geometry

输入：

$$
U_t
$$

输出：

$$
(\hat x_g,\hat y_g,\hat d,\hat\theta)
$$

指标：

$$
E_{\text{gaze}}
=
\frac1N
\sum_i
\sqrt{
(\hat x_i-x_i)^2+
(\hat y_i-y_i)^2
}
$$

以及 distance MAE：

$$
MAE_d=
\frac1N\sum_i|\hat d_i-d_i|
$$

---

### Task 2 — Difficulty Recognition

$$
(U_{1:t},S_{1:t},A_{1:t})
\rightarrow
D_t
$$

指标：

- Macro-F1
- AUROC
- balanced accuracy
- calibration/ECE

最重要的 ablation：

$$
S
$$

vs.

$$
S+A
$$

vs.

$$
S+U
$$

vs.

$$
\boxed{S+A+U}
$$

如果最后一个显著最好，我的核心 hypothesis 就成立了。

---

### Task 3 — Intervention Prediction

预测：

$$
P(I_t=1\mid U_{1:t},S_{1:t},A_{1:t})
$$

即：

> **现在应该帮助用户吗？**

这个问题甚至比 difficulty classification 更重要。

因为好的 adaptive system 必须知道：

$$
\boxed{\text{When NOT to intervene}}
$$

否则 Agent 会非常烦人。

---

### Task 4 — Adaptive Action

Agent 最终选择：

$$
a_t\in
\{
\text{None},
\text{Zoom},
\text{Highlight},
\text{Simplify},
\text{Explain},
\text{Voice},
\text{Execute}
\}
$$

最终评价：

$$
\Delta Success
$$

$$
\Delta Time
$$

$$
\Delta Errors
$$

$$
\Delta UserEffort
$$

以及：

$$
\text{Unnecessary Intervention Rate}
$$

---

# 13. 第一版算法不要太复杂

模型可以直接做三个 encoder。

### User Encoder

$$
z_t^U=f_U(U_{t-k:t})
$$

例如：

VideoMAE / ViT / lightweight VLM。

### Screen Encoder

$$
z_t^S=f_S(S_{t-k:t})
$$

可以直接借鉴 UI-Hawk 的 history-aware 思路。UI-Hawk 本身就是通过 history-aware visual encoder 建模 screen sequence，并设计 UI grounding、referring、QA、summarization 四个基础任务。

### Interaction Encoder

$$
z_t^A=f_A(A_{t-k:t})
$$

用 Transformer 编码：

```text
CLICK(x,y)
SCROLL(up)
WAIT(4.2s)
CLICK(x,y)
BACK
```

---

# 14. 真正值得作为 Method Contribution 的地方

不要把：

> YOLO 换成 VLM

当算法贡献。

真正值得研究的是 **User–UI Alignment / Cross Attention**。

对于 user token：

$$
Z^U\in\mathbb R^{N_u\times d}
$$

和 UI tokens：

$$
Z^S\in\mathbb R^{N_s\times d}
$$

做：

$$
Q=Z^U W_Q
$$

$$
K=Z^S W_K,\qquad
V=Z^S W_V
$$

得到：

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

它的含义非常直观：

> **用户的这个行为，到底与屏幕上的哪个 UI element 有关系？**

例如：

```text
长时间 fixation
        ↓
     Cross Attention
        ↓
右上角 12px「医保码」
        ↓
visual difficulty
```

而不是简单判断：

> 老人好像很困惑。

这会让我的 method 更有技术含量。

---

# 15. 后训练可以成为最后一层

Dataset + Benchmark + supervised model 做通之后，再进入 Personalized GUI Agent。

定义 state：

$$
s_t=(U_t,S_t,A_{1:t})
$$

policy：

$$
\pi_\theta(a_t\mid s_t,u)
$$

其中 $u$ 是用户 representation。

reward 可以定义：

$$
\boxed{
R=
\lambda_1R_{\text{success}}
-\lambda_2C_{\text{steps}}
-\lambda_3C_{\text{effort}}
-\lambda_4C_{\text{error}}
-\lambda_5C_{\text{unnecessary intervention}}
}
$$

于是 agent 不只是：

> 把任务做完。

而是：

> **以尽可能低的用户认知/视觉/操作负担帮助这个特定用户完成任务。**

这时候才真正进入：

$$
\boxed{
\text{Personalized GUI Agent}
}
$$

而且不同用户：

$$
u_1\neq u_2
$$

即使面对：

$$
S_1=S_2
$$

最优动作也可能：

$$
a_1^*\neq a_2^*
$$

例如年轻用户：

> `Do nothing`

视力下降老人：

> `Zoom`

认知负担较高用户：

> `Simplify + Highlight`

这就是 personalization 的真正定义。

---

# 16. 和康春工作的关系也可以非常清楚

COAS2W 已经证明中国老年人的自然语言存在 omission、语序问题、成分错误和 redundancy，并构建了 contextual dataset；小型开源模型经过针对性 fine-tuning 后甚至可以超过更大的闭源模型。

所以我们两条路线可以被统一成：

$$
\text{What does the user mean?}
$$

康春：

$$
\boxed{
\text{Language}
\rightarrow
\text{Intent Understanding}
}
$$

你：

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

最后：

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

**先尽早和康春讨论任务设计和受试者招募**，而不是等模型写完再找她。她现有的中国老年人数据采集、annotation 和 user study 经验，对我 Dataset III 的设计可能比某个具体 backbone 更重要。

---

# 17. 最终论文只主张两个 Contribution

从现在开始就控制住 scope。

**Contribution 1 — Dataset + Benchmark**

> We introduce a synchronized user–GUI interaction dataset capturing user-facing camera streams, screen streams, and touch trajectories during controlled and real-world mobile tasks, enabling systematic evaluation of user difficulty understanding and adaptive mobile interaction.

**Contribution 2 — User-Adaptive Agent**

> We propose a User–UI multimodal model that jointly reasons over user state, screen history, and interaction trajectories to detect user difficulty and determine when and how the mobile interface should adapt.

不要把 gaze estimation、64 grids、人体姿态、老人、微信、GUI Agent、GRPO 各写成一个 contribution。

它们全部服务于上面两个贡献。

---

# 18. 实际执行顺序

严格按照这一条路线走：

**第 0 阶段：先和康春/老师确认 scope**
确认现有受试者资源、伦理审批、已有老年用户数据、是否已经有人做 Mobile Agent，避免重复。

**第 1 阶段：复现 baseline**
跑通 GazeCapture / mobile gaze estimation、UI-Hawk 类 screen understanding，并测试现有 VLM 对 user-state 的 zero-shot 能力。GazeCapture 官方数据、模型和代码均已公开；UI-Hawk 的代码和 FunUI benchmark 也已经公开。

**第 2 阶段：10–20 人 pilot**
不要马上招几百个老人。先验证前置摄像头是否真的能可靠捕获 gaze/distance/head pose，以及 difficulty 有没有可观察 signal。

**第 3 阶段：Controlled Dataset**
64-grid calibration + controlled UI difficulty tasks。这里把 annotation schema 和 benchmark 定下来。

**第 4 阶段：正式老年用户数据采集**
加入真实年龄分布、不同手机经验、不同视觉/操作能力。涉及真实用户和生理/行为数据时，正式采集前先走学校伦理/知情同意与隐私流程。

**第 5 阶段：China Mobile Tasks**
通过访谈得到真实任务，而不是我自己猜老人需要什么。

**第 6 阶段：Benchmark paper experiments**
系统比较：

$$
Screen
\rightarrow
Screen+History
\rightarrow
Screen+Interaction
\rightarrow
Screen+User
\rightarrow
\boxed{Screen+Interaction+User}
$$

**第 7 阶段：User–UI Model**
做 temporal modeling + cross-modal alignment。

**第 8 阶段：真实 adaptive intervention study**
真正证明：

$$
\boxed{
\text{User-aware Agent}
>
\text{GUI-only Agent}
}
$$

而不是只证明 difficulty classification F1 高。

**第 9 阶段：Personalized Post-training**
如果前面已经足够形成一篇强论文，这一步完全可以拆成第二篇，而不要为了“GRPO”硬塞进第一篇。

---

最后，我会把整个项目用这一张逻辑图钉死：

```text
                 Existing GUI Agent
                        │
             Screen + Instruction
                        │
                        ▼
                      Action
                        │
             ───────────┼───────────
                        │
                 Missing modality
                        │
                        ▼
                      USER
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
        Face          Gaze        Head/Distance
          │             │             │
          └─────────────┼─────────────┘
                        ▼
                   User State
                        │
              + Screen History
              + Touch History
                        │
                        ▼
               Difficulty Reasoning
                        │
             ┌──────────┴──────────┐
             ▼                     ▼
       Do not intervene         Intervene
                                     │
                    ┌────────────────┼──────────────┐
                    ▼                ▼              ▼
                   Zoom          Highlight       Simplify
                                     │
                                     ▼
                         Adaptive Mobile Agent
                                     │
                                     ▼
                 Personalized Mobile Intelligence
```

**我现在最应该先做的不是设计模型，而是完成两个东西：① Dataset protocol v0.1；② 10–20 人 pilot 的变量表和 annotation schema。** 如果 pilot 能证明“用户困难确实能从 front camera + interaction dynamics 中被可靠观测，而且加入 user stream 显著优于 screen-only”，这项工作的核心 premise 就站住了；后面的 benchmark、User–UI model 和 personalized agent 都会顺理成章。
