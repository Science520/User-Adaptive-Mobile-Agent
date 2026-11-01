# R/S/M protocol v3

R=low search load（6选项），分easy/hard字形；S=high load（24选项）+easy字形；M=high load+hard字形。M是操控条件，不是困难真值。基础2×2只操控glyph height（32/20参考像素）及choice count（6/24），font weight=400、四块背景、潜在slot位置保持一致；语义相似度由同任务族词库配平并记录，本轮不同时随机改变8个因素。实际Android字形高度、背景及对比度仍需真机导出核对，PIL预览不是Android截图。

每Session24个不同target，所有其他Session target均从该Session distractors排除，避免提前暴露后续答案。允许重复干扰项，因此仍可能有界面熟悉化；按trial order分析。跨16个group轮换target的4个condition与4个zone，使用Williams四序列平衡条件顺序。pair_id是语义/任务族匹配，不表示重复同一图片或相同词。需要更多人后检查实际反应与自评，不预先宣称hard一定困难。

Assistance是独立研究模式：requested_only保留无预帮助、记录用户选择；assigned_pre_task在trial开始前随机分配，并单独报告。若随机条件下主动求助，标rescue_crossover，不混入原分配的纯比较。highlight_target=oracle正确位置强帮助；highlight_region=包含多选项的区域提示；二者不得等价比较。个人偏好、自评困难、实际有帮助三类字段分开。

R优先比较none/zoom_text/increase_contrast；S比较none/highlight_region/highlight_target/zoom_text；M先允许用户选择或随机单项，组合帮助作为明确的多次intervention序列记录，不能并成一个无定义标签。不要从单人的帮助前后速度推断因果收益。

R仍含少量搜索，S仍需读文字；必须用真实反馈检验任务区分性。Quick8每cell/zone各2项。最终匹配字段按domain+semantic_group+文字长度定义，randomization_block_id另存。某些匹配族在单Session可能只有1个目标，不得强行作一对一对照；跨参与者同词/位置轮换及实际matched_condition_id共同支持后续预先规定的比较。不能把索引相邻当语义匹配。

对于帮助收益应保留原assigned及crossover标签，不能看结果后改分组；研究前规定ITT/遵循协议分析口径。v3.1标签拒绝默认0分，允许无法评价或未提交；三种任务的困难依然以人类自报为准。暂停重试属于重复曝光例外，不能当首次独立trial。
