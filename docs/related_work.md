# 相关工作与来源核实

核实日期：2026-10-23。以下仅概述与设计相关的内容；未运行作者实验，也未下载其完整基准。

1. **From Faulty Memories to Corrected Actions / memory-rollback**
   - 作者代码：https://github.com/xiaoqi-7/memory-rollback
   - 论文 v2：https://arxiv.org/html/2608.10502v2
   - 已核实：依赖追踪、完整独立支持保留、规则化回滚与选择性重放；论文 3.2 明确把从原始自然语言日志推断缺失支持/生命周期边放在范围之外。
   - TracePatch 的区别：受控类型化记忆、按预算读取原始 capsule 恢复索引缺边，比较核验调度。本项目 graph_only 仅是轻量对照，不是作者实现的复现。

2. **MemoRepair: Barrier-First Cascade Repair in Agentic Memory**
   - 论文：https://arxiv.org/html/2605.07242v1
   - 已核实：先撤回、验证后发布、前驱闭合选择；默认采用修复收益/成本标量化目标的 min-cut，且讨论缺边泄漏敏感性。论文区分默认标量化选择与可选硬预算问题。
   - TracePatch 用统一有限规则核验器和硬工作单位上限检验调度，不复现论文的多类制品修复器或 min-cut。不能声称首次研究级联修复、预算代价或缺失 provenance。此次未确认可用官方代码。

3. **LongMemEval**
   - 官方仓库：https://github.com/xiaowu0162/LongMemEval
   - 已核实：覆盖信息提取、跨会话推理、知识更新、时态推理与拒答等能力。
   - 本项目数据完全自行生成；不以 LongMemEval 作为完整依赖 gold 来源，不报告官方基准成绩。

4. **LongMemEval-V2**
   - 官方仓库：https://github.com/xiaowu0162/LongMemEval-V2
   - 已核实：长期多模态 web-agent 轨迹、公开评估工具和 memory backend 接口，评价回答与查询延迟。
   - 可作为未来外部效度验证背景。此次没有审核其所有信息隔离细节，也没有下载/运行完整 web agent 数据，不把本项目接口隔离直接归因于该仓库。

5. **StateAuditor / When Memory Updates but Behavior Does Not**
   - 论文：https://arxiv.org/html/2608.01619v1
   - 已核实：研究当前记忆改变后响应中隐含旧依赖，采用 evidence/dependency/temporal 等核验角色；报告过度纠正与来源可追溯不等于语义正确的边界。
   - 本项目主要修复持久结构化状态，再做只读查询；不等价于其生成响应核验与改写流水线。

6. **工程适配背景**
   - Mem0：https://github.com/mem0ai/mem0 —— 长期记忆工程基础设施。
   - Graphiti：https://github.com/getzep/graphiti —— 面向 Agent 的时态知识/上下文图框架，强调来源与历史有效期。
   - 这里只作为未来接口适配背景，没有复现、部署或比较其最新系统表现。

7. **待核实线索**
   - Incremental Repair of Agent Memory and Plans after Business Evidence Revisions：
     https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7614038
   - 本次取全文返回 HTTP 403，未核实具体算法或比较结果，不据标题推断贡献。

候选研究切口是“不完整索引、可付费恢复的原始记录、有限核验预算”之间的取舍。机制组合和名称本身不能证明新颖性，发表价值还需更广查新、正式规模实验和真实应用验证。本项目不声明 SOTA、首次或普适有效。
