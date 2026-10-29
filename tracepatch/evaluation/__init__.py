"""Post-freeze private scorer. QueryReader never reads evidence or repairs."""
import csv
import random
from collections import defaultdict, Counter
from pathlib import Path
from ..common import read_json, write_json, typed_equal, digest
from ..domain import QueryReader
from ..experiment import verify_frozen, unseal


def ratio(a,b): return a/b if b else None


def score_state(records,gold,query_set):
    reader=QueryReader(records); rows=[]
    for q in gold["queries"][query_set]:
        answer=reader.query(q["logical_id"],q["owner_id"],q["scope_id"],q["at"],q["claim_key"])
        node=q["logical_id"]; answered=answer["outcome"]=="ANSWER"
        old_wrong=node!=gold["root"] and not typed_equal(gold["initial_values"][node],gold["true_values"][node])
        rows.append(dict(query_id=q["id"],logical_id=node,query_set=query_set,answer=answer["value"],gold=q["answer"],answered=answered,correct=answered and typed_equal(answer["value"],q["answer"]),root=node==gold["root"],old_wrong=old_wrong,stale=old_wrong and answered and typed_equal(answer["value"],gold["initial_values"][node])))
    current={}
    for m in records:
        if m["status"]=="ACTIVE" and m["valid_from"]<=1 and (m["valid_to"] is None or 1<m["valid_to"]): current[m["logical_id"]]=m["value"]
    original=set(gold["wrong_initial"]); all_ids=set(gold["true_values"]); benign=all_ids-original
    wrong={n for n,v in current.items() if not typed_equal(v,gold["true_values"][n])}
    correct_active={n for n,v in current.items() if typed_equal(v,gold["true_values"][n])}
    nonroot=all_ids-{gold["root"]}; original_nr=original&nonroot
    answered=sum(x["answered"] for x in rows); correct=sum(x["correct"] for x in rows)
    nonroot_rows=[x for x in rows if not x["root"]]
    root_rows=[x for x in rows if x["root"]]
    metrics={"questions":len(rows),"answered":answered,"correct":correct,"overall_accuracy":ratio(correct,len(rows)),"coverage":ratio(answered,len(rows)),"selective_accuracy":ratio(correct,answered),"stale_error_reuse":ratio(sum(x["stale"] for x in rows),sum(x["old_wrong"] for x in rows)),"stale_denominator":sum(x["old_wrong"] for x in rows),"root_accuracy":ratio(sum(x["correct"] for x in root_rows),len(root_rows)),"nonroot_accuracy":ratio(sum(x["correct"] for x in nonroot_rows),len(nonroot_rows)),"benign_unavailability":ratio(len(benign-correct_active),len(benign)),"global_wrong_active":ratio(len(wrong),len(all_ids)),"original_error_residual":ratio(len(wrong&original),len(original)),"nonroot_wrong_active":ratio(len(wrong&nonroot),len(nonroot)),"nonroot_error_residual":ratio(len(wrong&original_nr),len(original_nr)),"new_errors":len(wrong-original),"correct_recovery_count":len(correct_active&original),"wrong_active_ids":sorted(wrong),"benign_unavailable_ids":sorted(benign-correct_active)}
    return metrics,rows


def csv_write(path,rows):
    path=Path(path)
    if not rows: path.write_text("",encoding="utf-8"); return
    keys=list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w",newline="",encoding="utf-8-sig") as f:
        writer=csv.DictWriter(f,fieldnames=keys); writer.writeheader(); writer.writerows(rows)


METRICS=["overall_accuracy","coverage","selective_accuracy","stale_error_reuse","benign_unavailability","global_wrong_active","original_error_residual","nonroot_accuracy","nonroot_error_residual","root_accuracy","spent_units"]


def aggregate(rows,replicates=1000):
    bases=sorted(set(r["base_id"] for r in rows))
    rand=random.Random(20261023)
    samples=[[rand.choice(bases) for _ in bases] for _ in range(replicates)] if bases else []
    groups=defaultdict(dict)
    for r in rows: groups[(r["provider"],r["query_set"],r["delta"],r["budget"],r["method"])][r["base_id"]]=r
    def stats(values):
        present=[v for v in values.values() if v is not None]
        if not present: return None,None,None
        boot=[]
        for sample in samples:
            xs=[values[b] for b in sample if b in values and values[b] is not None]
            if xs: boot.append(sum(xs)/len(xs))
        boot.sort()
        return sum(present)/len(present),boot[int(.025*(len(boot)-1))],boot[int(.975*(len(boot)-1))]
    summary=[]
    for key,rs in sorted(groups.items(),key=lambda x:str(x[0])):
        provider,qs,delta,budget,method=key
        row=dict(provider=provider,query_set=qs,delta=delta,budget=budget,method=method,base_scenarios=len(rs),planned=len(rs),scored=sum(r["status"]!="failed" for r in rs.values()),failed=sum(r["status"]=="failed" for r in rs.values()))
        for metric in METRICS:
            mean,lo,hi=stats({b:r.get(metric) for b,r in rs.items()})
            row.update({metric:mean,metric+"_ci_low":lo,metric+"_ci_high":hi})
        summary.append(row)
    paired=[]
    for key,rs in groups.items():
        if key[-1]!="tracepatch": continue
        for comparator in ("expanded_fifo","graph_only","full_scan","root_only"):
            other=groups.get((*key[:-1],comparator),{})
            if not other: continue
            for metric in METRICS:
                diff={b:rs[b].get(metric)-other[b].get(metric) for b in rs.keys()&other.keys() if rs[b].get(metric) is not None and other[b].get(metric) is not None}
                mean,lo,hi=stats(diff)
                paired.append(dict(provider=key[0],query_set=key[1],delta=key[2],budget=key[3],comparison="tracepatch - "+comparator,metric=metric,paired_scenarios=len(diff),mean_difference=mean,ci_low=lo,ci_high=hi))
    return summary,paired,{"unit":"base_scenario","base_scenarios":len(bases),"replicates":replicates,"shared_sample_indices_hash":digest(samples),"samples":samples}


def evaluate(run,gold_dir):
    run=Path(run); gold_dir=Path(gold_dir)
    frozen,session=verify_frozen(run)
    episodes=[]; queries=[]; diagnostics=[]
    for item in frozen["runs"]:
        state=unseal(read_json(run/"states"/(item["run_id"]+".json")))
        gold=read_json(gold_dir/(item["base_id"]+".json"))
        shared={k:state[k] for k in ("run_id","base_id","method","budget","delta","provider","status")}
        for qs in ("usage","uniform"):
            if state["status"]=="failed":
                episodes.append(dict(shared,query_set=qs,reason=state.get("reason"))); continue
            m,qs_rows=score_state(state["records"],gold,qs)
            diagnostics.append(dict(shared,query_set=qs,wrong_active_ids=m.pop("wrong_active_ids"),benign_unavailable_ids=m.pop("benign_unavailable_ids")))
            episodes.append(dict(shared,query_set=qs,**m,**state["ledger"]))
            queries.extend(dict(shared,**row) for row in qs_rows)
        if state["status"]!="failed":
            candidate_actions=[a["result"] for a in state["actions"] if a["kind"]=="CANDIDATES"]
            supplement=set(candidate_actions[0]["semantic"]) if candidate_actions else set()
            obs=set(candidate_actions[0]["initial_observed"]) if candidate_actions else set()
            missed=(set(gold["wrong_initial"])-{gold["root"]})-obs
            diagnostics.append(dict(shared,semantic_candidate_recall=ratio(len(supplement&missed),len(missed)),recovered_edges=sum(a["kind"]=="EDGE" for a in state["actions"]),unknown_reasons=dict(Counter(r.get("reason") for r in state["results"].values() if r["outcome"]=="UNKNOWN")),true_edges=gold["true_edges"]))
    summary,paired,bootstrap=aggregate(episodes)
    csv_write(run/"per_episode.csv",episodes); csv_write(run/"per_query.csv",queries)
    csv_write(run/"metrics.csv",summary); csv_write(run/"paired_differences.csv",paired)
    write_json(run/"evaluation_diagnostics.json",diagnostics)
    write_json(run/"bootstrap.json",bootstrap)
    write_json(run/"evaluation.json",{"frozen_hash":read_json(run/"frozen_states.json")["hash"],"metrics":summary,"planned":frozen["planned"],"completed":frozen["completed"],"failed":frozen["failed"],"not_run":frozen["not_run"],"gold_hash":digest({p.name:read_json(p) for p in sorted(gold_dir.glob('*.json'))}),"per_episode_rows":len(episodes),"per_query_rows":len(queries)})
    return summary
