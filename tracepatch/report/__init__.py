"""Offline, escaped HTML and data-derived SVG plots; no CDN or web server."""
import html
import math
from pathlib import Path
from ..common import read_json, write_json, canonical
from ..experiment import verify_frozen, unseal


def esc(x): return html.escape(str(x),quote=True)
def number(x): return "NA" if x is None else f"{x:.3f}" if isinstance(x,float) else str(x)


def table(rows,columns):
    return '<table><thead><tr>'+''.join('<th>'+esc(title)+'</th>' for key,title in columns)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(number(r.get(key)))+'</td>' for key,title in columns)+'</tr>' for r in rows)+'</tbody></table>'


COLORS={"root_only":"#7b8495","graph_only":"#de8f45","expanded_fifo":"#aa74cf","tracepatch":"#15a999","full_scan":"#5086dc"}


def curve(rows,metric,title):
    # One chart per query distribution and edge condition, values from evaluation CSV source.
    w,h=680,330; left,top,right,bottom=65,45,25,65
    budgets=sorted(set(r["budget"] for r in rows if r["budget"] is not None)); maximum=max(budgets or [1]) or 1
    x=lambda b:left+(w-left-right)*b/maximum
    y=lambda v:top+(h-top-bottom)*(1-v)
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="{esc(title)}"><rect width="100%" height="100%" fill="white"/><text x="20" y="25" font-family="sans-serif" font-size="16">{esc(title)}</text>']
    for t in [0,.25,.5,.75,1]: parts.append(f'<line x1="{left}" y1="{y(t)}" x2="{w-right}" y2="{y(t)}" stroke="#e1e7ee"/><text x="20" y="{y(t)+5}" font-family="sans-serif" font-size="12">{t:.2f}</text>')
    for method in sorted(set(r["method"] for r in rows)):
        points=sorted((r["budget"],r[metric]) for r in rows if r["method"]==method and r["budget"] is not None and r.get(metric) is not None)
        color=COLORS.get(method,"#555")
        parts.append(f'<polyline points="'+" ".join(f"{x(b)},{y(v)}" for b,v in points)+f'" fill="none" stroke="{color}" stroke-width="2"/>')
        for b,v in points: parts.append(f'<circle cx="{x(b)}" cy="{y(v)}" r="4" fill="{color}"><title>{esc(method)}: B={b}, {v:.4f}</title></circle>')
    for b in budgets: parts.append(f'<text x="{x(b)-4}" y="{h-bottom+20}" font-family="sans-serif" font-size="12">{b}</text>')
    parts.append(f'<text x="{w/2-65}" y="{h-12}" font-family="sans-serif" font-size="13">Verification units</text></svg>')
    return ''.join(parts)


def graph_svg(records,edges,title):
    nodes=list({m["logical_id"]:m for m in records}.values())
    pos={m["logical_id"]:(60+(i%4)*200,55+(i//4)*95) for i,m in enumerate(nodes)}
    h=100+math.ceil(len(nodes)/4)*95
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 840 {h}" aria-label="{esc(title)}"><title>{esc(title)}</title><defs><marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" fill="#849bb3"/></marker></defs>']
    for a,b in edges:
        if a in pos and b in pos:
            x1,y1=pos[a]; x2,y2=pos[b]
            parts.append(f'<path d="M{x1+50},{y1+16} Q{x1+80},{y2-25} {x2+50},{y2-20}" stroke="#a9b6c7" fill="none" marker-end="url(#arrow)"/>')
    for m in nodes:
        x,y=pos[m["logical_id"]]; fill="#e2f5ef" if m["status"]=="ACTIVE" else "#fff0d3"
        parts.append(f'<rect x="{x-30}" y="{y-20}" width="175" height="40" rx="6" fill="{fill}" stroke="#b6c7d2"/><text x="{x-22}" y="{y-4}" font-family="sans-serif" font-size="10">{esc(m["text"][:17])}</text><text x="{x-22}" y="{y+11}" font-family="monospace" font-size="10">{esc(m["logical_id"][:7])} · {esc(m["value"])}</text>')
    return ''.join(parts)+"</svg>"


def report(run):
    run=Path(run); frozen,session=verify_frozen(run); evaluation=read_json(run/"evaluation.json")
    if evaluation["frozen_hash"]!=read_json(run/"frozen_states.json")["hash"]: raise ValueError("evaluation_is_stale")
    metrics=evaluation["metrics"]; figures=run/"figures"; figures.mkdir(exist_ok=True)
    title="TracePatch v0.2 · 长期记忆回归（v0.1 协议）"
    parts=[f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>:root{{color-scheme:light}}*{{box-sizing:border-box}}body{{margin:0;background:#f2f5f8;color:#233449;font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif}}main{{max-width:1240px;margin:auto;padding:38px}}h1{{font-size:34px;margin-bottom:4px}}h2{{margin-top:36px}}.eyebrow{{letter-spacing:3px;color:#138c80;font-weight:700}}.muted{{color:#66788e}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}.card,section,details{{background:white;border:1px solid #dce5ed;border-radius:12px;padding:20px;margin:15px 0}}.card strong{{display:block;font-size:28px}}table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{padding:9px;border-bottom:1px solid #e5ebf1;text-align:left;vertical-align:top;word-break:break-word}}th{{background:#edf4f8;position:sticky;top:0}}.scroll{{overflow:auto;max-height:650px}}.plots{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}svg{{max-width:100%}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fa;padding:14px;font-size:11px}}summary{{cursor:pointer;font-weight:650}}.tag{{padding:2px 8px;background:#e1f5ed;border-radius:20px}}.warn{{background:#fff5dc;border-left:4px solid #e2a735;padding:14px}}a{{color:#087f86}}@media(max-width:800px){{main{{padding:14px}}.cards,.plots{{grid-template-columns:1fr}}}}</style><main><div class="eyebrow">TRACE / VERIFY / REBUILD</div><h1>{title}</h1><p class="muted">有限核验预算 × 不完整依赖 · 固定证据快照 · 只读复用评价</p>''']
    parts.append('<div class="cards">'+''.join(f'<div class="card">{esc(label)}<strong>{esc(value)}</strong></div>' for label,value in [("计划运行",frozen["planned"]),("已完成（含预算停止）",frozen["completed"]),("失败 / 未运行",f'{frozen["failed"]} / {frozen["not_run"]}'),("实际模式",session["provider"])])+"</div>")
    parts.append('<p class="warn">这是一组受控结构化机制实验。smoke 仅用于工程验收；不能据此证明真实自然语言 Agent 的效果。旧错误复用指修复后仍读取旧值，本版不模拟新的写入污染。风险分数是启发式，不是错误概率。</p>')
    parts.append(f'<p>本次矩阵执行耗时 {frozen["wall_seconds_this_invocation"]:.3f} 秒；独立基础场景 {len(set(i["base_id"] for i in frozen["runs"]))}。每个方法与预算均从相同初始快照独立运行。置信区间按基础场景配对 bootstrap，见 paired_differences.csv；没有显著性结论。</p>')
    parts.append('<p>图例：'+" · ".join(f'<span style="color:{c}">{m}</span>' for m,c in COLORS.items())+'</p>')
    for qs in ("usage","uniform"):
        parts.append(f'<h2>{"未来使用分布" if qs=="usage" else "均匀目标覆盖"}</h2>')
        qsrows=[r for r in metrics if r["query_set"]==qs]
        parts.append('<div class="plots">')
        for delta in sorted(set(r["delta"] for r in qsrows)):
            selected=[r for r in qsrows if r["delta"]==delta]
            for metric in ("overall_accuracy","stale_error_reuse"):
                svg=curve(selected,metric,f'{qs} · missing edges {delta} · {metric}')
                (figures/f'{qs}_{delta}_{metric}.svg').write_text(svg,encoding="utf-8")
                parts.append('<section>'+svg+'</section>')
        parts.append('</div><div class="scroll">'+table(qsrows,[("method","方法"),("delta","缺边率"),("budget","预算"),("overall_accuracy","准确率"),("coverage","覆盖率"),("selective_accuracy","有回答时正确率"),("stale_error_reuse","旧错复用"),("benign_unavailability","正确记忆不可用"),("spent_units","实际单位"),("base_scenarios","基础场景 n"),("failed","失败")])+"</div>")
    all_states=[unseal(read_json(run/"states"/(i["run_id"]+".json"))) for i in frozen["runs"]]
    cost=[]
    for method in session["config"]["methods"]:
        states=[s for s in all_states if s["method"]==method and s["status"]!="failed"]
        d={"method":method,"runs":len(states)}
        for key in ("spent_units","capsule_reads","source_reads","rule_evaluations","leaf_extractions","cache_hits","model_requests","candidate_records_scored","graph_visits","candidate_seconds","evidence_seconds"):
            d[key]=sum(s["ledger"].get(key,0) for s in states)
        cost.append(d)
    parts.append('<h2>实际成本账本（合计）</h2><p>工作单位只计核验；候选检索与图遍历另外计数、计时。金额未配置，报告不推算费用。</p><div class="scroll">'+table(cost,[(k,k) for k in cost[0]])+'</div>' if cost else '')
    parts.append('<h2>案例、证据与失败诊断</h2><p>下表是最终冻结状态的只读查询结果。展开后可查看已付费读取的原文、恢复边、支持证书和每个动作的单位。隐藏真图仅在评价诊断文件中提供。</p>')
    chosen=[]; seen=set()
    for s in all_states:
        key=(s["method"],s["budget"],s["delta"])
        if key not in seen or s["status"]=="failed": chosen.append(s); seen.add(key)
    for s in chosen:
        label=f'{s["method"]} · B={s["budget"]} · δ={s["delta"]} · {s["status"]} · {s["base_id"][:7]}'
        parts.append('<details><summary>'+esc(label)+'</summary>')
        if s["status"]=="failed": parts.append('<pre>'+esc(s.get("reason"))+'</pre></details>'); continue
        history={}
        for m in s["records"]: history.setdefault(m["logical_id"],[]).append(m)
        rows=[]
        for node,vs in history.items():
            first,last=vs[0],vs[-1]
            rows.append({"id":node[:8],"claim":first["text"],"before":first["value"],"after":last["value"] if last["status"]=="ACTIVE" else "ABSTAIN","status":last["status"],"reason":last.get("reason","unprocessed"),"versions":len(vs)})
        parts.append('<div class="scroll">'+table(rows,[("id","ID"),("claim","声明"),("before","初始"),("after","只读回答"),("status","状态"),("reason","原因"),("versions","版本数")])+'</div>')
        entry=next(i for i in frozen["runs"] if i["run_id"]==s["run_id"])
        public_path=Path(session["data_path"])/entry["public"]
        if public_path.exists():
            public=read_json(public_path)
            parts.append('<details><summary>修复前可见依赖图</summary>'+graph_svg(public["memories"],public["edges"],"Initial observed graph")+'</details>')
        parts.append('<details><summary>付费恢复后的可见依赖图</summary>'+graph_svg([vs[-1] for vs in history.values()],s["edges"],"Observed graph after paid reads")+'</details>')
        parts.append('<details><summary>完整动作与证据账本</summary><pre>'+esc(canonical(s["actions"]))+'</pre></details></details>')
    diag=read_json(run/"evaluation_diagnostics.json")
    examples=[d for d in diag if d.get("wrong_active_ids") or d.get("benign_unavailable_ids")][:12]
    parts.append('<details><summary>评价诊断：残留错误 / 正确但不可用</summary><pre>'+esc(canonical(examples))+'</pre></details>')
    parts.append('<h2>边界与交付记录</h2><p>有限运算、模板字段提取、深度至多 4。图含共享模板，不代表开放域任务多样性；未测试自然语言端到端、GPU 训练或真实模型质量。完全丢失的证据可保持 UNKNOWN；全量核验也不能凭 gold 补全。live/replay 的真实服务表现尚未执行，HTTP 行为仅由模拟测试验证。</p><p>机器可读文件：metrics.csv、per_episode.csv、per_query.csv、paired_differences.csv、actions.jsonl、frozen_states.json、protocol.lock.json、dataset_manifest.json、config_snapshot.json。SQLite 保留各运行版本、证书、边与预留账本。</p></main></html>')
    path=run/"report.html"; path.write_text(''.join(parts),encoding="utf-8")
    return path
