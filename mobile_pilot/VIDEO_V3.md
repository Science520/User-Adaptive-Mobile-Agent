# Mobile Pilot v3 — R / S / M

本轮先审计 `test1030_20261030_144219`，再生成新设计、同源压缩和时序缓存，最后增量修改Android。旧v1/v2 Session与原始MP4不迁移、不改标、不删除。用户原有VIDEO_V2.md修改保留。

- R：6个选项的文字辨认，含easy/hard字形；S：24个可读选项的查找；M：24项+较小字形。条件不等于真实困难标签。
- Full24项、Quick8项。Full每2×2 cell6项、每2×2屏幕区域6项；Quick各2项。每Session目标不重复，其他目标不作本Session干扰项。
- 16组跨参与者轮换目标的condition和zone，Williams顺序平衡。设置页选择counterbalance group0–15；词库/layout seed固定42，注视顺序种子另记，不把unused seed当随机化证据。
- requested_only：任务开始不预给帮助；用户可自选。assigned_pre_task：每项开始前按已保存随机分配呈现，首次UI已含该帮助。额外求助记rescue_crossover；不要混作纯随机干预收益。
- zoom_text / increase_contrast / highlight_region / highlight_target / enlarge_touch / explain / none分开。target highlight明确oracle；region提示若只剩1个候选也记oracle-equivalent，不能当普通放大。
- assistance_requested记录选择时间，intervention_onset使用实际UI draw时间（不是photon onset），与UI版本/截图对应；结束记录为逻辑事件时刻。截图版本保护防止旧状态配新截图。
- 新录制根Schema=`temporal-pilot-v3`，protocol_version=`mobile-pilot-rsm-v3`；新试次保存task_family、条件、研究模式、assigned/requested/delivered及自评，避免跨协议盲目合并。
- 录像和人脸分析后端保持video-first；新增实际analysis宽高/cropRect/rotation元数据以调查Live与MP4视野差异。尚未强制共用ViewPort裁剪，也未验证物理时间映射。未实测的码率模式不冒充设备已支持；压缩结论来自桌面同源派生视频。

报告入口：`reports/pilot_v3/RESULTS.md`。审计数据表：`audit_20261030/`；设计及真机图片：`design/`；压缩：`compression/`；缓存及阻塞原因：`temporal/`；构建与真机检查：`build/`。

## 完整命令

```bash
cd /Users/audrey/Desktop/Phone
# 仅使用现有数据、现有本地模型与依赖，不下载研究数据。
# 以下重跑应选新输出目录；已有审计、派生视频、窗口禁止覆盖。
.venv/bin/python -m usercamera pilot-v3-audit test1030_20261030_144219 \
  --output reports/pilot_v3/recheck_audit --private reports/pilot_v3/private/recheck_audit
.venv/bin/python -m usercamera pilot-v3-design \
  --output reports/pilot_v3/recheck_design --asset data/derivatives/pilot_v3/recheck_protocol.json
# 当前压缩/窗口命令复用本轮标准审计目录的117帧引用；换原件前必须先核对其hash。
.venv/bin/python -m usercamera pilot-v3-compress test1030_20261030_144219 \
  --output reports/pilot_v3/recheck_compression --derived data/derivatives/pilot_v3/recheck_video
.venv/bin/python -m usercamera pilot-v3-temporal test1030_20261030_144219 \
  --output reports/pilot_v3/recheck_temporal --private reports/pilot_v3/private/recheck_temporal
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
cd mobile_pilot
./gradlew testDebugUnitTest assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n org.usercamera.mobilepilot/.MainActivity
```

现有真实Session复核：`pilot-video-verify`继续支持v1/v2，并支持v3的相同视频/Touch核心结构；v1/v2原任务含义保留。v3任务新Schema不能直接送旧v1/v2自评提取器。`pilot-v3-*`和private缓存只作本次单人feasibility准备，不输出未验证同步的融合性能。

原始人脸、逐帧生物特征、视频/压缩版/训练clips留在data或private；无网络和麦克风权限，不自动上传。控制界面示例不含人脸，PIL预览与实际Android截图分目录标记。

实际clip/单帧cache的可复用命令（保持标准39窗口引用，另选新clip输出目录以保留已有产物）：

```bash
cd /Users/audrey/Desktop/Phone
.venv/bin/python -m usercamera pilot-v3-cache \
  --private reports/pilot_v3/private/recheck_temporal \
  --video data/derivatives/pilot_v3/test1030_20261030_144219/h264_720w_2mbps.mp4 \
  --derived data/derivatives/pilot_v3/recheck_training_clips \
  --output reports/pilot_v3/recheck_temporal
```

所有clip仅包含截止前实际采样帧，记录原PTS和clip相对PTS，不把最后一帧播放保持时长当额外观察。当前窗口/裁剪是10月30日原件的引用，换原件时必须先做匹配审计，不能复用另一视频的frame IDs。

最终0.4.1同时修正helpfulness标签：有实际帮助时主动评分或选“无法评价”，没帮助时为不适用/null，未提交反馈保持missing。`self-report-v3.1`与旧0分语义分开，不改原数据。新匹配族与randomization_block_id分开；某些语义族在单Session只有一个成员，不能把它们强行当成配对对照。计划目标不重复，暂停重试仍可能重复曝光；需按attempt记录并单独处理学习效应，不把retry当独立首次试次。


## 小模型评估入口

```bash
cd /Users/audrey/Desktop/Phone
.venv/bin/python -m usercamera pilot-v3-evaluate \
  --private reports/pilot_v3/private/cache_module_recheck \
  --output reports/pilot_v3/recheck_evaluation \
  --prefix 2 --recent 2 --label difficulty \
  --algorithms logistic,hist_gradient_boosting,gru
```

当前数据预期输出 `status=blocked`：视频对齐未验证、只有一个独立Session，且选出的6个trial困难标签均为1。`--label future_help` 是后续求助预测，不能当无求助=无困难。当前没有拟合模型，也没有accuracy/F1；合格数据上的训练路径尚待实测。重复评估须换新的output目录，保留历史结果。
