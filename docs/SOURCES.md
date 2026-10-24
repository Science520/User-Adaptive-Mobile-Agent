# 实际使用的来源

核查日期：2026-10-21。下载清单保存官方返回的实际元数据，下载文件的内容哈希优先于网页显示规模。

| 来源 | 核实与实现 | 许可 / 局限 |
| --- | --- | --- |
| [UI-Hawk EMNLP 2025](https://aclanthology.org/2025.emnlp-main.920/) 与 [官方实现](https://github.com/IMNearth/UIHawk) | history-aware screen encoder；grounding、referring、screen QA、summarization。User Input 指令与前置摄像头不是同一模态。当前项目没有复现 UI-Hawk | 论文用于界定研究问题，不作为已训练模型 |
| [MPIIFaceGaze](https://darus.uni-stuttgart.de/dataset.xhtml?persistentId=doi:10.18419/darus-3240) | 15 名参与者；官方说明 37,667 张额外标注人脸；`Data.zip` 为 957,192,215 bytes；按参与者抽样，保留 Calibration 和 28 列标注 | CC BY-NC-SA 4.0；非商业科研，须署名。头姿及 face center 为估计；笔记本域，无手机操作流 |
| [FunUI](https://huggingface.co/datasets/Earthiii/FunUI-Benchmark) | 直接读取 `tasks_cn/*.json` 四类任务和 `images_cn.zip`。当前 ZIP 为 1,245,882,805 bytes；不依赖 Viewer | 官方 card：CC BY-SA 4.0；完整任务中存在负例和直接带框坐标的问题，需明确评分分母 |
| [MobileViews](https://huggingface.co/datasets/mllmTeam/MobileViews) | `MobileViews_Apps_CompleteTraces/OneExample.zip` 为 45,330,097 bytes。读取其中 `states/state_*.json` 与 `screen_*.jpg`，使用图像实际宽高；解析 `actions.csv`，保留 `utg.js` 作为原始数据，不执行其中的 JS | 官方 card：MIT。示例只有一个采集 App，不能单独进行跨 App 泛化验证 |

MPIIFaceGaze 的 28 列（按 1 开始）：1 图像路径；2–3 屏幕 gaze px；4–15 六个人脸关键点；16–18 head rotation vector；19–21 head translation；22–24 face center；25–27 gaze target 3D；28 eye subset。gaze direction 由 `(target - face_center)` 归一化得到。代码中关键点/头姿/gaze 标签不会进入 H1 图像输入。

本次没有下载 GazeCapture、AitW、COAS2W、ElderBench、OpenPhone 或 DMD。它们仍可作为后续资源，但本文没有复核或承诺其当前获取条件，也未把设计文档中的访问描述当作已验证事实。

本实现为实验代码；使用数据及其派生物时保留各自许可、署名与引用义务，不能因为项目代码可用就假定所有源数据许可相同。
