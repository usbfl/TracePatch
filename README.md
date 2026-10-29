# TracePatch v0.2

[项目展示](https://usbfl.github.io/TracePatch/) · [实验与验收报告](https://usbfl.github.io/TracePatch/report.html) · [GitHub 发布说明](docs/GITHUB_DEPLOYMENT.md)

本仓库是源码与精选报告版，不包含原归档中的大型 SQLite 运行轨迹；使用下方命令可生成新的完整运行目录。原归档的 `MANIFEST.sha256` 未纳入此仓库，`release_manifest.json` 仍保留原验收信息。

**一条记忆被纠正后，相关结论、当前任务和后续写回怎样一起更新？**

这是在 v0.1 源码上增量升级的离线研究项目。保留长期记忆修复引擎，新增当前用途调度、工作状态栏、计划接续，以及“摘要 → 写入 → 再检索 → 下一任务”的三轮闭环。

Python 3.11+、SQLite、标准库；CPU 即可运行。默认无需安装依赖、无需 API key。短期任务由确定性执行器运行，**本版没有验证真实 LLM Agent 的续做能力**。

## 先看什么

- [固定案例报告](docs/demo.html)：固定案例，六种方法 × 有/无旧摘要重放，共 12 个演示运行。
- [正式实验报告](docs/report.html)：新版正式 smoke，8 个独立场景、576 个条件运行。
- `docs/v0.2_design.md`：项目概览、结构、实验设计、已实现与待研究部分。
- `validation_report.txt`：本次实际验收结果和未执行事项。
- `validation/legacy_smoke.txt` 与 `validation_report.txt`：原有长期修复实验回归记录；原始报告可在本地重建。

报告可直接双击，不需要启动服务；页面预算下拉框可以筛选实际结果。

## 运行新版演示

在解压后的 `TracePatch` 根目录打开终端。使用新的输出目录：

Windows PowerShell：

```powershell
python -m tracepatch v2-demo --out runs/my_demo
Invoke-Item runs/my_demo/dev/report.html
```

也可运行 `powershell -ExecutionPolicy Bypass -File .\run_v2_demo.ps1`。
如果电脑使用 Python Launcher，把 `python` 替换为 `py -3`。

Linux / macOS：

```bash
python3 -m tracepatch v2-demo --out runs/my_demo
# macOS: open runs/my_demo/dev/report.html
# Linux: xdg-open runs/my_demo/dev/report.html
```

或者 `bash run_v2_demo.sh`。脚本只执行离线 Python 命令。

## 运行新版实验

```bash
python -m tracepatch v2-smoke --config configs/workflow_smoke.json --out runs/my_smoke
```

命令依次生成数据、运行 dev、冻结协议、运行 test、只读评分和生成报告。默认 dev=144 次，test=576 次：

`8 基础场景 × 2 缺边率 × 3 预算 × 2 当前用途 × 6 方法 = 576`。

每个运行执行 3 轮写回与再使用。576 不是独立样本量；独立基础场景只有 8 个，报告将条件副本先在场景内聚合。主 smoke 启用旧摘要重放压力；演示同时提供关闭重放的对照。

修改 `configs/workflow_smoke.json` 可以调整 `budgets`、`deltas`、`focuses`、`legacy_replays`、`rounds`、场景数、`semantic_k`。修改后使用新目录，重新 dev 和冻结，不复用旧 test 数据作调参结论。配置采用 JSON，无需 YAML 库。

中断恢复：

```bash
python -m tracepatch v2-smoke --config configs/workflow_smoke.json --out runs/my_smoke --resume
```

要求源码、配置、数据保持一致。恢复以带校验的 `.checkpoints/` 中的最新编号检查点 为准，`.sqlite` 是关闭时导出的查询副本，运行目录需整体保留。恢复已提交原子事件不重复逻辑收费；已有冻结结果只校验并复用。工程失败不会被当作成功或静默删除，修复代码后应创建新运行。包内交付记录可阅读和只读重评分；运行新的实验应使用新目录。

只读评分或重建报告：

```bash
python -m tracepatch v2-evaluate --run runs/my_smoke/test --gold runs/my_smoke/dataset/evaluation
python -m tracepatch v2-report --run runs/my_smoke/test
```

## 方法对应关系

| 新版方法 | 长期修复引擎 | 工作状态与写回 |
|---|---|---|
| `append_only` | 仅更正根 | 追加更正，保留旧的派生判断 |
| `source_refresh` | 仅更正根 | 刷新来源槽位，保留派生判断 |
| `replan` | 同预算全量扫描 | 从已核验信息重建固定任务计划，不保留完成标记 |
| `graph_local` | 沿可见依赖修复 | 同步可用结论，隐藏依赖仍可能漏修 |
| `tracepatch_state` | 图 + 文本候选 + 当前任务优先 | 更新状态，保留有效工作，重开失效步骤 |
| `tracepatch_guard` | 同上一方法 | 再检查写回声明的版本、值、主体、范围与时间 |

全部共享证据与核验器。当前用途来自更正到来时冻结的任务前缀，不读取未来评价问题。文本相似度只用于找候选，实际修改必须读证据并核验。新增写回检查复用已有证书，不读取新原文；比较次数单列，核验单位不是全部运行成本。

## 本版范围

已实现：长期修复兼容；用途优先；可观察状态、TODO 和预算；完成判断复核；受控格式摘要；绑定来源的写回门禁；按范围与时间过滤的文本索引；三轮继续使用；四种上下文投影；冻结、SQLite 事件、恢复与失败定位。持久化校验问题及修正记录见 `docs/persistence_validation.md`。

边界：不是通用自然语言推理器；“重规划”是固定任务集合上的状态重建；旧摘要回流来自可开关的压力注入；不是模型产生旧错误概率的测量。上下文仅报告字符数与共同前缀，实际 token、缓存命中与价格未测量。

时间变化与范围并存沿用 `TemporalStore` 边界 API，未扩展为主实验。Agentic RAG 多轮自主检索、向量嵌入索引、真实模型续做、自由文本语义写回核验、KV Cache 编辑及 GameReach 集成仍待研究。

## 源码入口

| 路径 | 作用 |
|---|---|
| `tracepatch/repair/`、`verify/`、`evidence/` | v0.1 核验与修复，新增用途提示 |
| `tracepatch/workflow/runtime.py` | 状态、计划、上下文、写回和再使用 |
| `tracepatch/workflow/experiment.py` | 共享前缀、协议冻结、矩阵与恢复 |
| `tracepatch/workflow/evaluate.py` | 冻结后读 gold，计算指标和失败位置 |
| `tracepatch/workflow/report.py` | 离线 HTML 报告 |
| `tests/test_workflow.py` | 新增机制与恢复测试 |

原 CLI 保留，`python -m tracepatch demo --out runs/long_term_demo --provider offline` 运行原长期演示；`python scripts/run_smoke.py --out runs/long_term_smoke` 跑原五方法矩阵。原运行说明存于 `docs/v0.1_archive/README.md`，归档中的旧计数不代表新版结果。

## 测试与校验

```bash
python -m pip install -e ".[test]"
python -m pytest -q
python scripts/validate_v2.py runs/v2_demo/dev runs/v2_smoke/dev runs/v2_smoke/test
```

pytest 是唯一必需的测试依赖，运行演示不需要它。首次安装测试依赖可能访问包服务。Linux 已实际验收，Windows/macOS 命令已提供但未实机验收。

## 真实模型仍默认关闭

原 `live/replay` 叶证据提取接口保留，详见 `docs/live_and_replay.md`。只有显式 `--provider live --allow-network` 才允许请求；环境中存在 key 不会自动启用。本轮没有真实模型调用。

新版 `v2-*` 命令只提供离线模式，防止把叶提取接口误称为真实 Agent 续做实验。接入模型需要先实现任务动作、摘要结构、语义核验及服务端 token 记录的适配器，然后另行冻结研究协议。
