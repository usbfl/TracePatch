"""Private post-freeze evaluation; runtime never imports this module."""
from collections import defaultdict
from pathlib import Path
from ..common import read_json, write_json, typed_equal, digest, file_hash
from ..evaluation import score_state, ratio, csv_write
from ..experiment import unseal


def equal(value, target):
    return value is not None and typed_equal(value, target)


def score(result, gold):
    """All denominators are fixed by the original prefix or gold, not successes."""
    prefix = result["prefix"]; truth = gold["true_values"]; initial = gold["initial_values"]
    steps = prefix["steps"]; actions = result["continuation"]["actions"]
    targets = {s["target"] for s in steps}
    old_wrong = {n for n in targets if not typed_equal(initial[n], truth[n])}
    benign_done = {s["id"] for s in steps if s["status"] == "DONE" and typed_equal(s["binding"]["value"], truth[s["target"]])}
    correct_actions = sum(equal(a["value"], truth[a["target"]]) for a in actions)
    retained = {a["step_id"] for a in actions if a["reused_work"] and equal(a["value"], truth[a["target"]])}
    current = {c["logical_id"]: c["value"] for c in result["state"]["claims"]}
    repaired = {n for n in old_wrong if equal(current.get(n), truth[n])}
    reused_stale = sum(a["target"] in old_wrong and equal(a["value"], initial[a["target"]]) for a in actions)
    cycle_rows = []; first_failure = None
    if any(a["value"] is not None and not equal(a["value"], truth[a["target"]]) for a in actions):
        first_failure = "initial_continuation"
    elif any(a["value"] is None for a in actions):
        first_failure = "initial_abstention"
    for cycle in result["cycles"]:
        written = cycle["written"]; by_id = {c["logical_id"]: c for c in cycle["retrieved"]}
        wrong_written = [c for c in written if not equal(c["value"], truth[c["logical_id"]])]
        reintroduced = {c["logical_id"] for c in wrong_written if c["logical_id"] in repaired}
        if first_failure is None and wrong_written: first_failure = f"write_round_{cycle['round']}"
        cycle_rows.append({"round": cycle["round"], "writes": len(written), "wrong_writes": len(wrong_written),
                           "repaired_then_wrong_write": len(reintroduced), "repairable_denominator": len(repaired),
                           "stale_retrieval_count": sum(n in by_id and equal(by_id[n]["value"], initial[n]) for n in old_wrong),
                           "old_wrong_denominator": len(old_wrong),
                           "next_task_accuracy": ratio(sum(equal(a["value"], truth[a["target"]]) for a in cycle["next_actions"]), len(steps)),
                           "next_task_coverage": ratio(sum(a["value"] is not None for a in cycle["next_actions"]), len(steps))})
    final = cycle_rows[-1]
    gates = [g for cy in result["cycles"] for g in cy["checks"]]
    comparisons = sum(g["comparisons"] for g in gates)
    rejected = [r for g in gates for r in g["rejected"]]
    metrics = {"task_accuracy": ratio(correct_actions, len(steps)), "task_success": int(correct_actions == len(steps)),
               "task_coverage": ratio(sum(a["value"] is not None for a in actions), len(steps)),
               "next_action_correct": int(equal(actions[0]["value"], truth[actions[0]["target"]])),
               "effective_work_retention": ratio(len(retained & benign_done), len(benign_done)),
               "valid_done_denominator": len(benign_done), "redo_count": sum(a["simulated_tool_call"] and s["status"] == "DONE" for a, s in zip(actions, steps)),
               "simulated_tool_calls": sum(a["simulated_tool_call"] for a in actions),
               "stale_action_reuse": ratio(reused_stale, len(old_wrong)), "old_wrong_denominator": len(old_wrong),
               "repaired_before_write": len(repaired), "recontamination_rate": ratio(final["repaired_then_wrong_write"], len(repaired)),
               "final_stale_retrieval": ratio(final["stale_retrieval_count"], len(old_wrong)),
               "final_task_accuracy": final["next_task_accuracy"], "final_task_coverage": final["next_task_coverage"],
               "guard_comparisons": comparisons, "rejected_writes": len(rejected),
               "rejected_correct_claims": sum(isinstance(r.get("claim"),dict) and equal(r["claim"].get("value"), truth.get(r["claim"].get("logical_id"))) for r in rejected),
               "context_characters": result["context"]["characters"], "elapsed_seconds": result["elapsed_seconds"],
               "first_failure": first_failure, "spent_units": result["repair"]["ledger"]["spent_units"],
               "model_requests": result["model_requests"], "actual_tokens": None, "cached_tokens": None}
    context_rows = []
    for mode, context in result["context_trials"].items():
        visible = {c["logical_id"]: c["value"] for c in context["effective_claims"]}
        context_rows.append({"context_mode": mode, "scripted_task_accuracy": ratio(sum(equal(visible.get(n), truth[n]) for n in targets), len(targets)),
                             "scripted_coverage": ratio(sum(n in visible for n in targets), len(targets)),
                             "characters": context["characters"], "common_prefix_characters": context["common_prefix_characters"],
                             "actual_tokens": None, "cached_tokens": None})
    return metrics, cycle_rows, context_rows


METRICS = ("task_accuracy", "task_success", "task_coverage", "next_action_correct", "effective_work_retention",
           "redo_count", "stale_action_reuse", "recontamination_rate", "final_stale_retrieval", "final_task_accuracy",
           "final_task_coverage", "guard_comparisons", "rejected_correct_claims", "spent_units", "elapsed_seconds")


def aggregate(rows):
    # First average the repeated conditions inside each base; variants are not independent observations.
    groups = defaultdict(lambda: defaultdict(list))
    for row in rows:
        groups[(row["method"], row["budget"])][row["base_id"]].append(row)
    results = []
    for (method, budget), bases in sorted(groups.items()):
        out = {"method": method, "budget": budget, "base_scenarios": len(bases),
               "planned": sum(len(rs) for rs in bases.values()),
               "failed": sum(r["status"] == "failed" for rs in bases.values() for r in rs)}
        for key in METRICS:
            base_values = []
            for rs in bases.values():
                vals = [r[key] for r in rs if r.get(key) is not None]
                if vals: base_values.append(sum(vals)/len(vals))
            out[key] = ratio(sum(base_values), len(base_values))
            out[key+"_n"] = len(base_values)
        results.append(out)
    return results


def verify_bundle(run):
    run = Path(run); frozen = unseal(read_json(run/"frozen.json"))
    protocol = unseal(read_json(run/"protocol.lock.json"))
    if read_json(run/"protocol.lock.json")["hash"] != frozen["protocol_hash"]:
        raise ValueError("protocol_modified")
    for rel, expected in frozen["files"].items():
        if file_hash(run/rel) != expected: raise ValueError("frozen_output_modified: "+rel)
    return frozen, protocol


def evaluate_bundle(run, gold_dir):
    run = Path(run); frozen, protocol = verify_bundle(run)
    rows, cycles, contexts, queries, long_rows, diagnoses = [], [], [], [], [], []
    for entry in frozen["runs"]:
        shared = {k: entry[k] for k in ("run_id", "base_id", "method", "budget", "delta", "focus", "legacy_replay", "status")}
        result = unseal(read_json(run/entry["state_path"]))
        if result["status"] == "failed":
            rows.append(dict(shared, reason=result["reason"])); continue
        gold = read_json(Path(gold_dir)/(entry["base_id"]+".json"))
        m, cy, co = score(result, gold)
        rows.append(dict(shared, **m)); cycles.extend(dict(shared, **r) for r in cy); contexts.extend(dict(shared, **r) for r in co)
        for qs in ("usage", "uniform"):
            lm, lr = score_state(result["repair"]["records"], gold, qs)
            diagnoses.append(dict(shared, query_set=qs, wrong_active_ids=lm.pop("wrong_active_ids"), benign_unavailable_ids=lm.pop("benign_unavailable_ids")))
            long_rows.append(dict(shared, query_set=qs, **lm))
            queries.extend(dict(shared, **r) for r in lr)
    summary = aggregate(rows)
    for filename, values in (("per_episode.csv", rows), ("metrics.csv", summary), ("cycles.csv", cycles),
                             ("contexts.csv", contexts), ("long_term.csv", long_rows), ("per_query.csv", queries)):
        csv_write(run/filename, values)
    write_json(run/"diagnostics.json", diagnoses)
    report = {"frozen_hash": read_json(run/"frozen.json")["hash"], "gold_hash": digest({p.name: file_hash(p) for p in sorted(Path(gold_dir).glob('*.json'))}),
              "metrics": summary, "planned": len(frozen["runs"]), "completed": sum(r["status"] == "completed" for r in rows),
              "failed": sum(r["status"] == "failed" for r in rows), "not_run": 0,
              "model_requests": sum(r.get("model_requests", 0) for r in rows),
              "unit": "base_scenario", "independent_scenarios": len({r["base_id"] for r in rows}),
              "limitation": "Engineering smoke with scripted actions and injected legacy summaries; no LLM or cache effect inference.",
              "csv_hashes": {p.name:file_hash(p) for p in run.glob('*.csv')}}
    write_json(run/"evaluation.json", report)
    return report
