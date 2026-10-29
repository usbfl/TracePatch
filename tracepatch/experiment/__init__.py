"""Protocol freeze, independent runs, deterministic recovery, immutable outputs."""
import json
import time
from pathlib import Path
from ..common import digest, file_hash, read_json, write_json, source_hash, RULE_VERSION, PROMPT_VERSION, FEATURE_VERSION
from ..storage import Journal
from ..evidence import EvidenceGateway
from ..verify import Verifier
from ..verify.providers import Extractor, ApiQuota, load_replay
from ..repair.context import RepairContext
from ..repair import Scheduler


def load_config(path):
    # Shipped .yaml files use JSON syntax, a strict YAML 1.2 subset. No PyYAML needed.
    cfg=read_json(path)
    if any(type(b) is not int or b<0 for b in cfg["budgets"]): raise ValueError("invalid_budget")
    allowed={"root_only","graph_only","expanded_fifo","tracepatch","full_scan","full_audit","all_quarantine","no_semantic","no_usage","no_cost"}
    if not set(cfg["methods"])<=allowed: raise ValueError("unknown_method")
    return cfg


def verify_data(data,manifest):
    for rel,expected in manifest["files"].items():
        path=Path(data)/rel
        if not path.is_file() or file_hash(path)!=expected: raise ValueError("data_integrity_mismatch: "+rel)
    if digest(manifest["files"])!=manifest["content_hash"]: raise ValueError("manifest_mismatch")


def seal(obj):
    obj=dict(obj); obj["hash"]=digest(obj); return obj


def unseal(obj):
    obj=dict(obj); expected=obj.pop("hash",None)
    if digest(obj)!=expected: raise ValueError("frozen_hash_mismatch")
    return obj


def freeze_protocol(run,out):
    run=Path(run); session=unseal(read_json(run/"session.json"))
    if session["split"]!="dev": raise ValueError("freeze_requires_dev")
    summary=unseal(read_json(run/"frozen_states.json"))
    if any(x["status"]=="failed" for x in summary["runs"]): raise ValueError("dev_has_failed_runs")
    protocol={"config":session["config"],"source_hash":session["source_hash"],"dataset_manifest":session["manifest"],"verifier_mode":session["verifier_mode"],"model":session["model"],"versions":{"rules":RULE_VERSION,"prompt":PROMPT_VERSION,"features":FEATURE_VERSION},"analysis":{"unit":"base_scenario","bootstrap_replicates":1000,"bootstrap_seed":20261023,"metrics_version":"exact-readonly-1"},"dev_state_hash":read_json(run/"frozen_states.json")["hash"]}
    write_json(out,seal(protocol)); return protocol


def run_one(public,environment,method,budget,cfg,dbpath,provider="offline",model=None,allow_network=False,quota=None,replay=None,crash_after=None,crash_pending=None):
    binding={"public_hash":digest(public),"method":method,"budget":budget,"config":cfg,"source_hash":source_hash(),"mode":"offline" if provider=="offline" else "model","model":model or {}}
    journal=Journal(dbpath,binding,budget,crash_after,crash_pending)
    try:
        gateway=EvidenceGateway(environment,public["snapshot_id"],journal)
        extractor=Extractor(provider,journal,model,allow_network,quota,replay,run_id=digest(binding))
        context=RepairContext(public,gateway,journal,extractor.mode)
        verifier=Verifier(context,extractor,cfg.get("max_depth",4))
        policy_config={k:cfg[k] for k in ("semantic_k","weights")}
        # v0.2 purpose hints are current task inputs, never future evaluation queries.
        policy_config["focus_targets"]=cfg.get("focus_targets",[])
        status=Scheduler(context,verifier,method,policy_config).run()
        journal.finish(status)
        result={"status":status,"method":method,"budget":budget,"records":context.records(),"edges":sorted(context.graph),"certificates":context.certificates,"ledger":journal.ledger(),"results":context.results,"actions":journal.actions()}
        return result
    finally: journal.close()


def run_matrix(data,out,split="dev",config=None,protocol=None,provider="offline",allow_network=False,resume=False,replay_dir=None,model=None):
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    if resume:
        session=unseal(read_json(out/"session.json"))
        data=Path(session["data_path"])
        # Packages may be extracted under a different path; explicit --data overrides it.
        cfg=session["config"]; split=session["split"]; provider=session["provider"]
        model=session["model"]; manifest=session["manifest"]
        if session["source_hash"]!=source_hash(): raise ValueError("resume_source_changed")
        if (out/"protocol.lock.json").exists():
            p=unseal(read_json(out/"protocol.lock.json"))
            if digest(p["config"])!=digest(cfg): raise ValueError("resume_protocol_changed")
    else:
        if (out/"session.json").exists(): raise ValueError("run_exists_use_resume_or_new_directory")
        data=Path(data).resolve(); manifest=read_json(data/"manifest.json")
        mode="offline" if provider=="offline" else "model"
        if protocol:
            p=unseal(read_json(protocol)); cfg=p["config"]
            if p["source_hash"]!=source_hash() or p["dataset_manifest"]!=manifest or p["verifier_mode"]!=mode: raise ValueError("protocol_binding_mismatch")
            if model is not None and model!=p["model"]: raise ValueError("protocol_model_mismatch")
            model=p["model"]
            write_json(out/"protocol.lock.json",read_json(protocol))
        else:
            if split=="test": raise ValueError("test_requires_frozen_protocol")
            cfg=config
        model=model or cfg.get("model",{})
        session={"config":cfg,"source_hash":source_hash(),"manifest":manifest,"data_path":str(data),"split":split,"provider":provider,"verifier_mode":mode,"model":model,"replay_dir":str(Path(replay_dir).resolve()) if replay_dir else None}
        write_json(out/"session.json",seal(session))
    if read_json(data/"manifest.json")!=manifest: raise ValueError("dataset_manifest_changed")
    verify_data(data,manifest)
    if provider=="live" and not allow_network: raise ValueError("live_requires_allow_network")
    quota=ApiQuota(out/"api_quota.sqlite",cfg.get("max_api_attempts",32)) if provider=="live" else None
    replay=load_replay(replay_dir or session.get("replay_dir")) if provider=="replay" else None
    write_json(out/"config_snapshot.json",cfg)
    write_json(out/"dataset_manifest.json",manifest)
    if not (out/"protocol.lock.json").exists():
        write_json(out/"protocol.lock.json",seal({"kind":"dev_exploratory","config":cfg,"source_hash":source_hash()}))
    matrix=[]
    for entry in manifest["entries"]:
        if entry["split"]!=split: continue
        for method in cfg["methods"]:
            for budget in ([None] if method=="full_audit" else cfg["budgets"]):
                rid=digest([entry["variant_id"],method,budget])[:24]
                matrix.append(dict(entry,method=method,budget=budget,run_id=rid))
    started=time.perf_counter(); summary=[]; exported_actions=[]
    for item in matrix:
        rid=item["run_id"]; target=out/"states"/(rid+".json")
        if target.exists(): result=unseal(read_json(target))
        else:
            public=read_json(data/item["public"])
            try:
                result=run_one(public,data/item["environment"],item["method"],item["budget"],cfg,out/"db"/(rid+".sqlite"),provider,model,allow_network,quota,replay)
            except Exception as exc:
                result={"status":"failed","reason":type(exc).__name__+": "+str(exc),"records":[],"actions":[],"ledger":{}}
            result.update({k:item[k] for k in ("run_id","base_id","variant_id","delta","method","budget")},provider=provider)
            write_json(target,seal(result))
        summary.append({**item,"status":result["status"],"state_hash":read_json(target)["hash"]})
        exported_actions.extend(dict(a,run_id=rid) for a in result["actions"])
    if quota: quota.db.close()
    actions_path=out/"actions.jsonl"
    actions_path.write_text("".join(json.dumps(a,ensure_ascii=False)+"\n" for a in exported_actions),encoding="utf-8")
    frozen={"runs":summary,"planned":len(matrix),"completed":sum(x["status"] in {"completed","budget_exhausted"} for x in summary),"failed":sum(x["status"]=="failed" for x in summary),"not_run":0,"session_hash":read_json(out/"session.json")["hash"],"protocol_hash":read_json(out/"protocol.lock.json")["hash"],"config_hash":digest(read_json(out/"config_snapshot.json")),"actions_hash":file_hash(actions_path),"wall_seconds_this_invocation":time.perf_counter()-started}
    write_json(out/"frozen_states.json",seal(frozen))
    return frozen


def verify_frozen(run):
    run=Path(run); frozen=unseal(read_json(run/"frozen_states.json")); session=unseal(read_json(run/"session.json"))
    if read_json(run/"session.json")["hash"]!=frozen["session_hash"] or digest(read_json(run/"config_snapshot.json"))!=frozen["config_hash"]: raise ValueError("frozen_config_modified")
    unseal(read_json(run/"protocol.lock.json"))
    if read_json(run/"protocol.lock.json")["hash"]!=frozen["protocol_hash"] or file_hash(run/"actions.jsonl")!=frozen["actions_hash"]: raise ValueError("frozen_protocol_or_actions_modified")
    for item in frozen["runs"]:
        state=read_json(run/"states"/(item["run_id"]+".json")); unseal(state)
        if state["hash"]!=item["state_hash"]: raise ValueError("frozen_state_modified")
    return frozen,session
