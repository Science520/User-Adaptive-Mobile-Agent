数据集设置：
垂直于人眼固定 x cm 的位置照相
把手机分为64块 或者多少块，制作一个图让人明显识别到这些块（像视力表，字体大小，人眼变化？）
人眼距离手机也为 x cm
手机距离人眼 x cm，手机前置摄像头照人脸位置
人脸数据，人眼数据

变量：
字体大小，人眼和手机距离，人眼和手机角度

需要去除干扰项：
手机和人手相对于人眼的角度

最后数据集：
图像数据：垂直于人眼拍摄的图片；手机前置摄像头拍摄照片

可比较算法：
- 车载系统识别车内人姿势动作；眼动仪相关捕捉注意力算法
- Camera → VLM / detector → event recognition → notification识别算法，模型可以换成 YOLO、VideoMAE、VLM
- 2026 年 EACL 的 MLLM-HCI tutorial 已经把 conversational GUI agents、accessibility、inclusive applications 放到同一个研究框架里；ACL 2026 的 OpenPhone甚至已经研究 SFT→GRPO 训练 mobile GUI agent
- 2026 年 9 月刚出现 ElderBench：249 个真实老年人 smartphone tasks、20 个 App，发现主流 GUI agents 在老人自然表达下明显退化。ElderBench 恰恰发现老人自然指令中的 indirect speech、referential ambiguity、under-specification 是当前 agent 的明显困难
- UI-Hawk 已经说明 screen-stream history 对 GUI agent 很重要，而不仅仅是看当前 screenshot
- 新的 GB/T 47523-2026《移动互联网应用程序适老化技术规范》 已在 2026 年发布，将于 2026-11-01 实施“https://www.miit.gov.cn/jgsj/xgj/wjfb/art/2021/art_81e8b738d6b24ad6a04f7ecb3f4e0702.html?utm_source=chatgpt.com”

自身算法：
关系链：手机 - 手 - 身体 - 头 - 眼睛
头和眼也有夹角，手连接身体胸腔到脖子到头是直接建模这一条传导线。
还是思考如何统一抽象为眼睛和手机夹角

手机摄像头：
- 自己的位置（与手机关系）
- 捕获画面长宽
- 焦距影响
- 自动补齐头部，推理与眼的关系

手机内具体内容：
- 屏幕分布
- 与整体收关系关系

人手：
- 与手机关系
- 与人体身体和头部关系

头：
- 头与手关系

眼睛：
- 与头关系
- 看手机角度


目标：
- 面向中国复杂移动生态的、用户状态感知的 Adaptive Mobile AI / GUI Agent Harness。Adaptive Mobile Intelligence in China's Super-App Ecosystem




实时识别某个用户此刻是否遇到困难，并动态适配
Older-user speech
        ↓
Intent understanding
        ↓
GUI Agent
        ↓
Screen interaction
        ↓
User-state sensing
        ↓
Difficulty detection
        ↓
Adaptive intervention