"""Self-contained offline report. Every displayed number comes from frozen output."""
import csv
from html import escape
from pathlib import Path
from ..common import read_json, file_hash
from ..experiment import unseal
from .evaluate import verify_bundle

NAMES = {"append_only": "只追加更正", "source_refresh": "只刷新来源", "replan": "全量重规划",
         "graph_local": "沿已有依赖修复", "tracepatch_state": "TracePatch 状态修复", "tracepatch_guard": "TracePatch + 写回检查"}


def pct(x): return "—" if x is None else f"{x:.1%}"
def num(x): return "—" if x is None else f"{x:.2f}"
def val(x): return "待核验" if x is None else "成立" if x is True else "不成立" if x is False else str(x)


def report(run):
    run = Path(run); frozen, protocol = verify_bundle(run); ev = read_json(run/"evaluation.json")
    if ev["frozen_hash"] != read_json(run/"frozen.json")["hash"]: raise ValueError("evaluation_stale")
    for p,h in ev["csv_hashes"].items():
        if file_hash(run/p) != h: raise ValueError("evaluation_csv_modified")
    rows = []
    for m in ev["metrics"]:
        rows.append(f'<tr data-budget="{m["budget"]}"><td>{escape(NAMES[m["method"]])}</td><td>{m["budget"]}</td><td>{pct(m["task_accuracy"])}</td><td>{pct(m["effective_work_retention"])}</td><td>{pct(m["final_task_accuracy"])}</td><td>{pct(m["final_stale_retrieval"])}</td><td>{pct(m["recontamination_rate"])}</td><td>{num(m["spent_units"])}</td></tr>')
    # One shared concrete prefix, show all methods at the largest budget under stress.
    chosen = next((r for r in frozen["runs"] if r["method"] == "tracepatch_guard" and r["budget"] == max(protocol["config"]["budgets"]) and r["legacy_replay"]), frozen["runs"][0])
    same = [r for r in frozen["runs"] if all(r[k] == chosen[k] for k in ("base_id", "delta", "focus", "budget", "legacy_replay")) and r["status"] == "completed"]
    case = []; trace = ''; statebar = ''; context_table = ''
    for entry in same:
        state = unseal(read_json(run/entry["state_path"]))
        plans = state["state"]["plan"]; actions = state["continuation"]["actions"]
        for s,a in zip(plans,actions):
            case.append('<tr>'+''.join('<td>'+escape(str(x))+'</td>' for x in [NAMES[entry['method']], s['label'], val(s['binding']['value']), val(a['value']), s['status'], s['reason']])+'</tr>')
        if entry["method"] == "tracepatch_guard":
            statebar = '<ul>'+''.join('<li>'+escape(c['text'])+'</li>' for c in state['state']['claims'])+'</ul>'
            trace = ''.join('<details><summary>第 '+str(cy['round']+1)+' 轮：摘要 → 写入 → 再检索 → 下一任务</summary><p>接受 '+str(sum(len(g['accepted']) for g in cy['checks']))+' 条，拒绝 '+str(sum(len(g['rejected']) for g in cy['checks']))+' 条。</p><ul>'+''.join('<li>'+escape(r.get('claim',{}).get('text','未绑定文本'))+'：'+escape(r['reason'])+'</li>' for g in cy['checks'] for r in g['rejected'])+'</ul><p>再检索结果：'+escape('；'.join(c['text'] for c in cy['retrieved']))+'</p></details>' for cy in state['cycles'])
            context_table = '<table><thead><tr><th>上下文策略</th><th>字符数</th><th>相邻轮共同前缀字符</th><th>真实 token / 缓存命中</th></tr></thead><tbody>'+''.join(f'<tr><td>{escape(mode)}</td><td>{c["characters"]}</td><td>{c["common_prefix_characters"]}</td><td>未测量</td></tr>' for mode,c in state['context_trials'].items())+'</tbody></table>'
    with (run/'per_episode.csv').open(encoding='utf-8-sig') as f: detail_rows=list(csv.DictReader(f))
    failures = [r for r in detail_rows if r.get('first_failure')]
    failrows = ''.join('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in [NAMES[r['method']],r['budget'],r['focus'],r['first_failure'],r['task_accuracy'],r['final_task_accuracy']])+'</tr>' for r in failures[:12])
    budgets = sorted({m['budget'] for m in ev['metrics']})
    labels = [('接收更正','保留原轨迹与版本'),('找到关联','依赖图、文本与当前任务'),('核验并修复','预算网关与有限规则'),('接续任务','更新状态、重开失效步骤'),('检查写回','版本绑定、范围与时间'),('再检索验证','检查旧错误是否回流')]
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TracePatch v0.2 · 实验与项目说明</title><style>
:root{color-scheme:light;--ink:#13283e;--accent:#007d76;--muted:#52677c}*{box-sizing:border-box}body{margin:0;background:#f3f6f8;color:var(--ink);font:16px/1.65 system-ui,-apple-system,"Microsoft YaHei",sans-serif}main{max-width:1280px;margin:auto;padding:42px 32px 70px}header{background:#112a40;color:white;padding:44px;border-radius:20px}header small{color:#8ce0d5;letter-spacing:2px}h1{font-size:38px;line-height:1.2;margin:14px 0}h2{font-size:24px;margin:0 0 18px}h3{font-size:18px}p{max-width:1000px}section{background:white;border:1px solid #dbe4eb;border-radius:16px;padding:28px;margin-top:22px}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.card{padding:18px;border:1px solid #dde8ec;border-radius:12px}.card b{display:block;font-size:18px}.card small{color:var(--muted)}.stats{display:flex;gap:24px;flex-wrap:wrap;margin-top:24px}.stats b{display:block;font-size:30px;color:#8ce0d5}.notice{border-left:4px solid var(--accent);padding:10px 18px;background:#edf7f5}.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:12px 11px;text-align:left;border-bottom:1px solid #e0e7ed;vertical-align:top}th{background:#eef3f6;white-space:nowrap}td:first-child{min-width:160px}details{border-bottom:1px solid #dce5ea;padding:14px 0}summary{cursor:pointer;font-weight:650}select{padding:7px 14px;border:1px solid #b4c5d3;border-radius:6px;background:white;color:var(--ink)}code{background:#edf2f5;padding:2px 5px;border-radius:3px}footer{font-size:13px;color:var(--muted);padding-top:24px}@media(max-width:720px){main{padding:16px}header,section{padding:22px}.grid{grid-template-columns:1fr}h1{font-size:30px}}@media print{body{background:white}header{color:#112a40;background:white;border:2px solid #112a40}section{break-inside:avoid}select{display:none}}
</style><main><header><small>TRACEPATCH / VERSION 0.2 / OFFLINE</small><h1>纠正一条记忆，让后续任务也跟着改</h1><p>沿长期知识修复与短期任务接续两条主线，串起“更正 → 核验 → 状态更新 → 续做 → 摘要写回 → 再次使用”。</p>'''
    html += f'<div class="stats"><div><b>{ev["completed"]}/{ev["planned"]}</b>已完成运行</div><div><b>{ev["independent_scenarios"]}</b>独立基础场景</div><div><b>{ev["model_requests"]}</b>真实模型调用</div><div><b>{ev["failed"]}</b>工程失败</div></div></header>'
    html += '<section><h2>本版实际实现了什么</h2><div class="grid">'+''.join(f'<div class="card"><small>0{i+1}</small><b>{a}</b><small>{b}</small></div>' for i,(a,b) in enumerate(labels))+'</div><p class="notice">这是可运行的离线机制实验台。动作由确定性执行器产生，摘要使用绑定断言的受控格式；旧摘要重放是预设压力输入。结果不能直接推断真实 LLM 的理解、自然语言压缩或缓存收益。</p></section>'
    html += '<section><h2>共享前缀下的六种方法</h2><p class="muted">同一数据、纠正时点和核验预算。每基础场景先对缺边与用途条件取平均，再跨场景平均；本次是工程 smoke，不作显著性或优越性结论。</p><label>核验预算 <select id="budget"><option value="all">全部</option>'+''.join(f'<option value="{b}">{b}</option>' for b in budgets)+'</select></label><div class="tablewrap"><table id="metrics"><thead><tr><th>方法</th><th>预算</th><th>初次续做正确率</th><th>有效工作保留率</th><th>末轮正确率</th><th>末轮旧错复用</th><th>修好后再污染</th><th>实际核验单位</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div><p class="muted">“—”表示分母为零。再污染只在写回前已修正确的原错误目标中计算；旧错复用使用固定的原错误任务目标作分母。未知计入覆盖损失，不算正确。写回检查的内存比较次数单列在 metrics.csv，不冒充免费的模型核验。</p></section>'
    html += '<section><h2>看懂一个案例</h2><p>设备内存记录被纠正后，原先已完成的兼容性判断可能失效；低需求游戏和独立支持分支则可能继续成立。下面展示同一前缀在各方法中的实际变化。</p><div class="tablewrap"><table><thead><tr><th>方法</th><th>原任务</th><th>原判断</th><th>续做判断</th><th>计划状态</th><th>原因</th></tr></thead><tbody>'+''.join(case)+'</tbody></table></div><h3>修复后的状态栏</h3>'+statebar+'<h3>持续写回记录</h3>'+trace+'</section>'
    html += '<section><h2>上下文整理对照</h2><p>append 追加根更正；invalidate 撤下旧版本；replace 保留历史并替换末尾状态；rebuild 仅保留任务与有效状态。读取规则固定，比较的是消息处理机制。</p>'+context_table+'<p class="muted">共同前缀长度只表示文本的重叠，不等于服务端缓存命中。实际 token、缓存 token 与金额均未测量。</p></section>'
    html += '<section><h2>失败也保留在结果里</h2><p>initial_continuation 是首次续做仍用错值；initial_abstention 是预算或证据不足导致无法继续；write_round 是原本可继续、却在写回阶段引入错误。以下按运行顺序展示最多 12 个实例，完整记录见 CSV。</p><div class="tablewrap"><table><thead><tr><th>方法</th><th>预算</th><th>用途</th><th>首个偏离</th><th>初次正确率</th><th>末轮正确率</th></tr></thead><tbody>'+failrows+'</tbody></table></div></section>'
    html += '<section><h2>研究边界与下一步</h2><ul><li>继承 v0.1 的不完整依赖、证据网关、规则核验、SQLite 日志、版本与只读评分。</li><li>本版新增当前用途优先、状态栏、完成判断重开、三轮写回与检索、四种上下文投影。</li><li>时间更新与范围并存仍通过边界 API 验证，主实验只处理可信 CORRECTION。</li><li>尚未执行真实 Agent 续做、自然语言语义写回验证、Agentic RAG 多轮决策、嵌入索引或 KV Cache 编辑。</li><li>真实模型接口沿用 v0.1 的叶证据提取模式，需显式启用，不等于完整 Agent 接入。</li></ul><p>项目包内 README 提供运行命令，docs/v0.2_design.md 说明架构与实验口径；JSON / CSV / SQLite 保留原始结果。</p></section>'
    html += '<footer>TracePatch v0.2 · 报告由实际冻结结果生成 · 不依赖网络或 CDN · protocol '+escape(read_json(run/'protocol.lock.json')['hash'][:16])+'</footer></main><script>document.getElementById("budget").addEventListener("change",function(){document.querySelectorAll("#metrics tbody tr").forEach(r=>r.hidden=this.value!=="all"&&r.dataset.budget!==this.value)});</script></html>'
    (run/"report.html").write_text(html, encoding="utf-8")
    return run/"report.html"
