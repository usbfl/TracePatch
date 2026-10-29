# TracePatch v0.1

**一条记忆修正后，如何在有限预算内核验依赖它的推断与缓存，同时保留仍然正确的信息？**

本项目提供可运行的 CPU 离线实验台。Python 3.11+、SQLite、标准库，无运行时第三方依赖，不需要 API key、GPU、浏览器自动化、Node 或模型下载。HTML 报告直接用浏览器打开。

## 先运行 demo

在解压后的 `TracePatch` 目录打开终端。无需安装即可从项目根目录执行：

```powershell
python -m tracepatch demo --out runs/demo_local --provider offline
Invoke-Item runs/demo_local/report.html
```

Windows 也可运行 `powershell -ExecutionPolicy Bypass -File .\run_demo.ps1`。需要系统已安装 Python 3.11+；若使用 Python Launcher，将命令中的 `python` 替换为 `py -3`。不要重复使用已有输出目录；第二次可用 `--out runs/demo_local_2`。

Linux / macOS：

```bash
python3 -m tracepatch demo --out runs/demo_local --provider offline
# macOS: open runs/demo_local/report.html
# Linux: xdg-open runs/demo_local/report.html
```

或者 `bash run_demo.sh`。报告由本次代码运行生成。包内 `runs/demo/report.html` 是交付时实际生成的固定案例，`runs/smoke/test/report.html` 是正式 smoke 结果。

演示：设备内存一直是 8 GB，却被记录为 16 GB；虚构游戏 A 需要 12 GB，B 需要 6 GB。“推荐 A”是第二跳推断，且索引中隐藏了兼容性 A→推荐 A 的边。云端完整分支可以独立支持另一结论。五种方法分别跑 B=8 和 B=128，共 10 次。

## 安装与测试（可选）

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[test]"
.\.venv\Scripts\python -m pytest -q
```

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```

安装只需 setuptools；pytest 只用于测试。报告默认使用本地 SVG，避免 Matplotlib 成为运行必需依赖。`.[plots]` 可选装 Matplotlib 供后续自定义分析。隔离网络环境可以直接从源码运行 demo；不执行 pip 即不需要下载任何包。

## 一条命令重跑 smoke

```bash
python scripts/run_smoke.py --out runs/smoke_local
```

这会生成互不重叠的 8 个 dev、8 个 test 基础场景。各自运行 2 个缺边条件 × 2 个预算 × 5 个方法 = 160 次，再冻结协议、执行 test、评价和生成报告。只读评价不进行证据读取或新修复。

以下展开命令在 PowerShell 与 Bash 中通用（Linux 按环境换成 `python3`）：

```bash
python -m tracepatch data build --config configs/smoke.yaml --out data/smoke_local
python -m tracepatch run --config configs/smoke.yaml --data data/smoke_local --split dev --out runs/dev_local --provider offline
python -m tracepatch freeze-protocol --run runs/dev_local --out protocols/smoke_local.lock.json
python -m tracepatch run --protocol protocols/smoke_local.lock.json --data data/smoke_local --split test --out runs/test_local --provider offline
python -m tracepatch evaluate --run runs/test_local --gold data/smoke_local/evaluation
python -m tracepatch report --run runs/test_local
```

配置文件采用 JSON 语法（合法的 YAML 1.2 子集），因此无需 PyYAML。请保持双引号，不使用 YAML 的缩进式简写。pilot=4,320 个 test 运行；research 和压力配置不会自动启动。所有配置均支持相同 CLI，先 dev，再冻结，再 test。

## 方法与语义

| 方法 | 候选与调度 |
|---|---|
| root_only | 仅应用可信根更正 |
| graph_only | 可见后继，按距离、创建顺序、ID |
| expanded_fifo | 同 TracePatch 候选，按创建顺序、ID |
| tracepatch | 可见后继 + 一次性语义 TopK；风险 × 历史使用 / 可观察成本 |
| full_scan | 所有同作用域有效记忆，按创建顺序、ID |
| full_audit | 独立诊断参考；不限制预算，仍不能读取 gold |
| all_quarantine | 隔离全部非根的指标诊断 |
| no_semantic / no_usage / no_cost | 可运行消融；实际收费不变 |

修复使用 COPY/EQ/GE/LE/AND/OR/NOT 和严格 int/bool/string 类型；UNKNOWN 不是 FALSE。旧 ACTIVE 输入必须重新核验。根更正有可信证书，旧日志中的根版本绑定不会撤销更正。支持证书只保留足以决定结果的完整分支。

每次读取和执行先事务预留，再执行，再提交。工作单位不是金额。候选排序与图遍历另外计数、计时。预算不足下一原子操作时，整个运行停止核验；已完成子树保留，未完成节点隔离。

## 断点恢复

```bash
python -m tracepatch run --resume --out runs/test_local
```

SQLite journal 保存 pending、预留、已提交输出、版本、证书与边。恢复通过确定性重演控制流重建内存状态；已提交事件直接返回持久化输出，不增加请求、缓存命中、状态写入或费用。未提交离线原子操作沿用同一 ID 和预留。故障注入测试比较了动作顺序、账本与最终状态。

恢复要求原数据位置、源码、协议与配置保持一致。源码或语义配置变化请使用新输出目录、重新跑 dev 并冻结协议。交付结果是历史冻结产物，可以阅读、评价与报告；修改源码后不要把旧日志当作新版本实验。`failed` 行也保留在矩阵中；修复原因后重新建立运行，不会自动跳过失败样本。

## 真实模型入口（默认关闭）

见 [docs/live_and_replay.md](docs/live_and_replay.md)。只替换叶证据字段提取器；图、有限规则、调度与查询器不变。即使环境中已有 key，默认离线也绝不会发请求。必须同时使用 `--provider live --allow-network`。

构建与交付未调用任何真实模型。模拟 HTTP 测试不等于真实服务验证。

## 文件与研究边界

`public/` 是修复可见资料；`environment/` 只能经计费网关读取；`evaluation/` 只供冻结后的评分。策略接收的配置仅包含 K 与权重，生成种子与隐藏真图不交给策略。此隔离是接口/测试约束，不是抵御恶意 Python 的安全沙箱。

输出包含 `report.html`、三个主要 CSV、配对差分、完整 actions、冻结状态、协议、数据清单、配置、SVG 图和每运行 SQLite。详见 [docs/research_protocol.md](docs/research_protocol.md)、[docs/related_work.md](docs/related_work.md)、[docs/limitations.md](docs/limitations.md)、[validation_report.txt](validation_report.txt)。

主实验只处理已诊断、可信且定位到根的 CORRECTION；UPDATE 和 CONTEXTUAL_ASSERTION 由 `TemporalStore` 的独立边界 API 与测试覆盖。尚未连接真实 Agent 或 GameReach，也不训练模型权重。本项目不是 memory-rollback、MemoRepair、Mem0 或 Graphiti 的官方复现。
