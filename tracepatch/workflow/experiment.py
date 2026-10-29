"""Frozen-prefix paired workflows. Runtime, evaluation and artifact layers separate."""
from pathlib import Path
import itertools
import time
import sqlite3
from ..common import read_json, write_json, digest, file_hash, source_hash
from ..data import build_dataset, WEIGHTS
from ..experiment import seal, unseal, verify_data
from .runtime import METHODS, make_prefix, run_workflow


DEFAULT = {"name": "workflow-smoke-v2", "seeds": [20261029], "dev_scenarios": 2, "test_scenarios": 8,
           "nodes": [24, 32], "deltas": [0, 0.5], "budgets": [0, 16, 64], "methods": list(METHODS),
           "focuses": ["recommendation", "storage"], "legacy_replays": [True], "rounds": 3,
           "semantic_k": 16, "weights": WEIGHTS, "max_depth": 4, "capsule_loss": 0}


def validate_config(cfg):
    for name in ("dev_scenarios", "test_scenarios"):
        if type(cfg[name]) is not int or cfg[name] < 0: raise ValueError("invalid_scenario_count")
    if not cfg["methods"] or not set(cfg["methods"]) <= set(METHODS): raise ValueError("invalid_methods")
    if not cfg["budgets"] or any(type(b) is not int or b < 0 for b in cfg["budgets"]): raise ValueError("invalid_budgets")
    if not set(cfg["focuses"]) <= {"recommendation", "storage"} or not cfg["focuses"]: raise ValueError("invalid_focus")
    if not cfg["legacy_replays"] or any(type(v) is not bool for v in cfg["legacy_replays"]): raise ValueError("invalid_legacy_replay")
    if type(cfg["rounds"]) is not int or not 1 <= cfg["rounds"] <= 100: raise ValueError("invalid_rounds")
    for name in ("budgets", "methods", "focuses", "legacy_replays", "deltas", "seeds"):
        if len(cfg[name]) != len(set(cfg[name])): raise ValueError("duplicate_matrix_condition")


def make_protocol(cfg, manifest, kind, dev_hash=None):
    return seal({"version": "tracepatch-workflow-2", "kind": kind, "config": cfg,
                 "source_hash": source_hash(), "dataset_hash": manifest["content_hash"], "dev_hash": dev_hash,
                 "analysis": {"unit": "base_scenario", "status": "engineering_smoke_no_significance_claim",
                              "context": "scripted_decoder_no_cache_measurement", "budget": "repair_units_guard_comparisons_separate"}})


def run_split(data, out, split, protocol, resume=False, progress=None):
    data, out = Path(data), Path(out)
    spec = unseal(protocol); cfg = spec["config"]; validate_config(cfg)
    if spec["source_hash"] != source_hash(): raise ValueError("protocol_source_changed")
    manifest = read_json(data/"manifest.json"); verify_data(data, manifest)
    if spec["dataset_hash"] != manifest["content_hash"]: raise ValueError("protocol_dataset_changed")
    if split == "test" and (spec["kind"] != "test_frozen" or not spec["dev_hash"]): raise ValueError("test_requires_dev_freeze")
    if out.exists() and not resume: raise ValueError("output_exists_choose_new_directory")
    if resume and (out/"frozen.json").exists():
        from .evaluate import verify_bundle
        frozen, saved = verify_bundle(out)
        if read_json(out/"protocol.lock.json") != protocol:
            raise ValueError("resume_protocol_changed")
        return frozen
    out.mkdir(parents=True, exist_ok=True)
    lock = out/"protocol.lock.json"
    if lock.exists() and read_json(lock) != protocol: raise ValueError("resume_protocol_changed")
    write_json(lock, protocol)
    write_json(out/"dataset_manifest.json", manifest)
    write_json(out/"config_snapshot.json", cfg)
    runtime_cfg = {k: cfg[k] for k in ("semantic_k", "weights", "max_depth")}
    entries = [e for e in manifest["entries"] if e["split"] == split]
    matrix = list(itertools.product(entries, cfg["methods"], cfg["budgets"], cfg["focuses"], cfg["legacy_replays"]))
    results = []; started = time.perf_counter()
    for i, (entry, method, budget, focus, legacy) in enumerate(matrix):
        rid = digest([entry["variant_id"], method, budget, focus, legacy])[:24]
        state_path = "states/"+rid+".json"; target = out/state_path
        public = read_json(data/entry["public"]); prefix = make_prefix(public, focus)
        if target.exists():
            state = unseal(read_json(target))
        else:
            try:
                state = run_workflow(public, data/entry["environment"], prefix, method, budget, runtime_cfg,
                                     out/"db"/rid, rounds=cfg["rounds"], legacy_replay=legacy)
            except Exception as exc:
                state = {"status": "failed", "reason": type(exc).__name__+": "+str(exc)}
            write_json(target, seal(state))
        results.append({"run_id": rid, "base_id": entry["base_id"], "variant_id": entry["variant_id"],
                        "method": method, "budget": budget, "delta": entry["delta"], "focus": focus,
                        "legacy_replay": legacy, "status": state["status"], "prefix_hash": digest(prefix),
                        "state_path": state_path})
        if progress and (i+1) % 24 == 0: progress(f"{split}: {i+1}/{len(matrix)}")
    files = {str(p.relative_to(out)).replace('\\','/'): file_hash(p) for p in sorted((out/"states").glob('*.json'))}
    result_paths = {r["run_id"]: r["state_path"] for r in results}
    # Validate closed databases, and bind their exact bytes into the final seal.
    # A completed computation alone does not certify its recovery log.
    for path in sorted((out/"db").rglob("*.sqlite")):
        db = sqlite3.connect(":memory:")
        try:
            db.deserialize(path.read_bytes())
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("closed_database_integrity_failed: "+str(path))
            state = unseal(read_json(out/result_paths[path.parent.name]))
            if state["status"] == "completed":
                repair_db = path.stem == "repair"
                ledger = state["repair"]["ledger"]
                expected = (ledger["spent_units"] if repair_db else 0, 0,
                            state["repair"]["status"] if repair_db else "completed")
                if db.execute("SELECT spent,reserved,status FROM run").fetchone() != expected:
                    raise ValueError("closed_database_ledger_mismatch: "+str(path))
                expected_count = len(state["repair"]["actions"] if repair_db else state["actions"])
                if db.execute("SELECT count(*) FROM actions").fetchone()[0] != expected_count:
                    raise ValueError("closed_database_actions_mismatch: "+str(path))
        finally:
            db.close()
        files[str(path.relative_to(out)).replace('\\','/')] = file_hash(path)
    for path in sorted((out/"db").rglob("*.json")):
        files[str(path.relative_to(out)).replace('\\','/')] = file_hash(path)
    for name in ("dataset_manifest.json", "config_snapshot.json"):
        files[name] = file_hash(out/name)
    frozen = {"protocol_hash": protocol["hash"], "files": files, "runs": results,
              "elapsed_seconds": time.perf_counter()-started}
    write_json(out/"frozen.json", seal(frozen))
    return frozen


def run_suite(out, cfg=None, demo=False, resume=False, progress=print):
    from .evaluate import evaluate_bundle
    from .report import report
    out = Path(out); cfg = cfg or dict(DEFAULT)
    if demo:
        cfg = dict(DEFAULT, name="workflow-demo-v2", dev_scenarios=1, test_scenarios=0,
                   nodes=[24,24], deltas=[0], budgets=[64], focuses=["recommendation"], legacy_replays=[False,True])
    validate_config(cfg)
    if out.exists() and not resume: raise ValueError("output_exists_choose_new_directory")
    if not (out/"dataset"/"manifest.json").exists(): build_dataset(cfg, out/"dataset", demo=demo)
    manifest = read_json(out/"dataset"/"manifest.json")
    if manifest["generation_config_hash"] != digest(cfg): raise ValueError("resume_config_changed")
    dev_protocol = make_protocol(cfg, manifest, "dev_exploratory")
    dev = run_split(out/"dataset", out/"dev", "dev", dev_protocol, resume, progress)
    evaluate_bundle(out/"dev", out/"dataset"/"evaluation"); report(out/"dev")
    if any(r["status"] == "failed" for r in dev["runs"]): raise ValueError("dev_failed_protocol_not_frozen")
    if cfg["test_scenarios"]:
        protocol = make_protocol(cfg, manifest, "test_frozen", read_json(out/"dev"/"frozen.json")["hash"])
        write_json(out/"protocol.lock.json", protocol)
        run_split(out/"dataset", out/"test", "test", protocol, resume, progress)
        result = evaluate_bundle(out/"test", out/"dataset"/"evaluation"); path = report(out/"test")
    else:
        result = read_json(out/"dev"/"evaluation.json"); path = out/"dev"/"report.html"
    return {"report": str(path.resolve()), **{k:result[k] for k in ("planned", "completed", "failed", "model_requests")}}
