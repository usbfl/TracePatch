# v0.2 相关工作与实现依据

检索核对日期：2026-10-29。以下是直接相关的一手来源。此处是机制对照，不是系统性查新，也没有复现这些工作的官方实验成绩。

| 来源 | 与本项目的关系 | 本版区别与限制 |
|---|---|---|
| [Dependency-Guided Rollback Repair，arXiv 2608.10502 v2](https://arxiv.org/abs/2608.10502v2)，[作者代码](https://github.com/xiaoqi-7/memory-rollback) | 依赖回滚、保留独立支持与选择性重放 | 本版研究部分依赖缺失与当前用途预算，使用自建合成引擎；不是官方复现 |
| [MemoRepair](https://arxiv.org/abs/2605.07242) | 先撤回受影响状态、验证后重发布、成本权衡 | 本版未实现其最大权闭包 / min-cut 选择器，不把级联修复本身作为新颖性 |
| [StateAuditor](https://arxiv.org/abs/2608.01619) | 存储更新后行为仍受旧状态影响 | 本版仅验证结构化状态与写回边界，没有复现其模型驱动的语义转变审计 |
| [Anthropic：Effective harnesses for long-running agents](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents) | 通过明确进度、可读产物和验证维持跨上下文任务接续 | 借鉴可观察任务状态，不声称其方法证明本项目纠错效果 |
| [LangChain：Improving Deep Agents with harness engineering](https://www.langchain.com/blog/improving-deep-agents-with-harness-engineering) | 分析执行轨迹、核验完成情况并据此改进运行框架 | 采用阶段日志和首个偏离定位，本轮未进行 Agent 自动优化 Harness |

最新用户思路文档把长期更新与短期上下文两条路线并列，并要求持续写回检查。实现依据保存在 source_plan_2026-10-27.txt；它是输入方案，不是实验结论。

更早的相关工作记录见 related_work.md。v0.2 实际完成范围以 README、v0.2_design.md 和 validation_report.txt 为准。
