# v0.2 验收对应

| 能力 | 实现 | 验证 |
|---|---|---|
| 原五方法长期修复 | repair / verify / evidence | 原 67 项测试与原 smoke 重跑 |
| 当前用途调度 | Scheduler focus_targets | 首次核验目标与两种用途的矩阵 |
| 状态栏与计划接续 | workflow/runtime.py | 错误 DONE 重开、正确 DONE 保留、未知等待 |
| 防止旧错写回 | WriteGuard | 错值、伪版本、主体/范围/时间错误拒绝；同值版本重绑定 |
| 摘要文字与结构一致 | 规范声明重建文字 | 假文字及注入文本不能被原样写回 |
| 连续再使用 | SUMMARY/WRITE/RETRIEVE/NEXT_TASK | 三轮执行，旧错回流与无重放对照 |
| 上下文策略 | project_context | append/invalidate/replace/rebuild 的确定性读取 |
| 恢复 | SQLite Journal | pending 和 committed 中断后状态/事件/预算一致 |
| 信息隔离 | 运行与 evaluate 分离 | 删除 evaluation 后仍可修复；原 gold 非干扰测试 |
| 冻结验证 | 协议和文件哈希 | 配置/状态修改拒绝；完整目录恢复不改协议 |
| 外部模型默认关闭 | v2 CLI 仅离线 | 存在 key 时禁止 socket 的参数化测试 |

真实执行结果见 validation_report.txt 和 validation/。未执行：真实模型端到端接续、真实缓存测量、自由文本语义写回、外部基准、Windows/macOS 实机。
