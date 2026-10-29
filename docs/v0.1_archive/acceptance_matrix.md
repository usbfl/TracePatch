# 规格验收映射

| 规格范围 | 实现/产物 | 验证方式 |
|---|---|---|
| 领域、版本、三值逻辑 | domain、repair/context、verify | bool/int 分离、真假/UNKNOWN、完整支持、版本与时态边界测试 |
| 三层隔离 | data、EvidenceGateway、RepairContext | 无 evaluation 仍运行；改 gold 不改动作；策略只接收 K/权重 |
| 付费 capsule 与原文 | evidence、storage | 预留、长度/哈希、不存在读取、恢复边付费出处 |
| 候选、排序、五基线 | repair | TopK 一次构造；FIFO 同池；graph-only 不语义扫描；三个消融均可执行 |
| 固定示例 | demo CLI、runs/demo | 五方法 × 低/高预算；逐记录表、依赖图、证据/动作账本 |
| 数据与嵌套掩码 | data、configs | 场景约束断言；独立随机流；dev/test 场景与实体隔离 |
| 预算与停止 | storage、verify | B=0、递归收费、预算不透支、一次拒绝后全局停止 |
| 持久化与恢复 | SQLite action journal | pending/committed 故障注入、相同动作序列/状态/账本、重复运行幂等 |
| live / replay | verify/providers | 显式双开关、HTTP 模拟、限次、全局 API 配额、uncertain 不重发、记录哈希校验 |
| 只读查询与指标 | domain/QueryReader、evaluation | 手算分母、NA、全隔离、同值后继、旧错与新错分离 |
| 协议与冻结 | experiment | test 需 lock、源码/数据/配置绑定、状态修改检测 |
| 统计与报告 | evaluation、report、plot_metrics.py | 配对基础场景 bootstrap、CSV 对照、转义、离线 HTML/SVG/Matplotlib |
| 主 smoke | runs/smoke | 160 dev + 160 test，实际执行记录 |
| 完整性 | Journal.finish、最终验证 | 新连接 SQLite integrity_check，版本投影/预算与冻结 JSON 对照 |
| 相关工作 | related_work.md | 一手论文/官方仓库核实；SSRN 403 单列 |
| 压力与大规模 | configs | 可运行预设；未默认跑满，执行状态见 validation_report |

没有将真实模型、Windows/macOS 实机运行、外部自然语言基准或浏览器视觉验收冒充已通过。没有把 pilot/research 配置冒充正式结果。统计结果只用于受控机制与工程验收。
