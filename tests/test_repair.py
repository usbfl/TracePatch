import json
import hashlib
import shutil
from copy import deepcopy
from pathlib import Path
import pytest
from tracepatch.common import canonical, read_json, write_json, typed_equal
from tracepatch.experiment import run_one
from tracepatch.storage import Journal, InjectedCrash
from tracepatch.evidence import EvidenceGateway
from tracepatch.verify import Verifier
from tracepatch.verify.providers import Extractor
from tracepatch.repair.context import RepairContext
from tracepatch.repair import similarities
from tracepatch.evaluation import score_state


def logical_actions(result): return [{k:v for k,v in a.items() if k!="seconds"} for a in result["actions"]]
def logical_ledger(result): return {k:v for k,v in result["ledger"].items() if not k.endswith("seconds")}


def rewrite_cap(env,m,fn):
    index=read_json(env/"index.json"); meta=index["capsule"][m["capsule_id"]]; path=env/meta["path"]
    cap=read_json(path); fn(cap); body=canonical(cap).encode(); path.write_bytes(body)
    meta.update(bytes=len(body),sha256=hashlib.sha256(body).hexdigest()); write_json(env/"index.json",index)


def test_demo_full_repair_preserves_correct_and_stops_old_root(execute_episode,episode):
    state=execute_episode(); public,env,gold,cfg=episode
    current={m["logical_id"]:m for m in state["records"] if m["status"]=="ACTIVE"}
    for m in public["memories"]:
        assert m["logical_id"] in current
        assert typed_equal(current[m["logical_id"]]["value"],gold["true_values"][m["logical_id"]])
    assert state["ledger"]["spent_units"]<=128
    assert any(r["new_value"] is False for r in state["results"].values())
    assert state["ledger"]["model_requests"]==0


def test_durable_database_integrity_and_version_projection(episode,tmp_path):
    import sqlite3
    public,env,gold,cfg=episode
    path=tmp_path/"durable.sqlite"
    state=run_one(public,env,"full_audit",None,cfg,path)
    db=sqlite3.connect(path)
    assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
    assert db.execute("SELECT count(*) FROM versions").fetchone()[0]==len(state["records"])
    assert db.execute("SELECT spent,reserved FROM run").fetchone()==(state["ledger"]["spent_units"],0)
    db.close()


def test_baselines_candidate_fairness_and_no_root_side_effect(execute_episode,episode):
    root=execute_episode("root_only",128)
    assert root["ledger"]["spent_units"]==0 and not root["results"]
    assert len(root["records"])==len(episode[0]["memories"])+1
    a=execute_episode("tracepatch",0); b=execute_episode("expanded_fifo",0)
    ca=lambda s:next(x["result"] for x in s["actions"] if x["kind"]=="CANDIDATES")
    assert ca(a)==ca(b)
    assert len(ca(a)["semantic"])<=16
    assert len([x for x in a["actions"] if x["kind"]=="SELECT" and x["args"]["stage"]=="initial_semantic"])==1


def test_graph_only_no_semantic_and_semantic_no_causal_edges(episode,tmp_path):
    public,env,gold,cfg=episode; public=deepcopy(public); public["edges"]=[]
    state=run_one(public,env,"graph_only",128,cfg,tmp_path/"g.sqlite")
    assert state["ledger"]["spent_units"]==0 and state["edges"]==[]
    state=run_one(public,env,"tracepatch",0,cfg,tmp_path/"s.sqlite")
    assert state["edges"]==[] and state["ledger"]["capsule_reads"]==0


@pytest.mark.parametrize("budget",[0,1,2,3,8,17])
def test_budget_never_overspends_and_stops_globally(execute_episode,budget):
    r=execute_episode("tracepatch",budget)
    assert r["ledger"]["spent_units"]<=budget and r["ledger"]["reserved_units"]==0
    denials=[a for a in r["actions"] if a["status"]=="denied"]
    if denials:
        assert len(denials)==1
        assert not any(a["kind"] in {"READ_CAPSULE","READ_SOURCE","RULE","EXTRACT"} for a in r["actions"] if a["seq"]>denials[0]["seq"])
    if budget==0: assert r["ledger"]["bytes_read"]==0


def test_recovered_edges_require_paid_capsule(execute_episode):
    r=execute_episode(); actions={a["action_id"]:a for a in r["actions"]}
    recovered=[a for a in r["actions"] if a["kind"]=="EDGE"]
    assert recovered
    for a in recovered:
        read=actions[a["result"]["read_action_id"]]
        assert read["kind"]=="READ_CAPSULE" and read["units"]>=1 and read["status"]=="committed"


def test_missing_capsule_cannot_use_gold_and_independent_branch_requires_all(episode,tmp_path):
    public,env,gold,cfg=episode
    index=read_json(env/"index.json")
    license_node=next(m for m in public["memories"] if m["text"].startswith("云端游玩授权"))
    (env/index["capsule"][license_node["capsule_id"]]["path"]).unlink()
    r=run_one(public,env,"full_audit",None,cfg,tmp_path/"x.sqlite")
    independent=next(m for m in public["memories"] if "本地或云端" in m["text"])
    assert r["results"][independent["logical_id"]]["outcome"]=="UNKNOWN"
    assert r["results"][license_node["logical_id"]]["reason"]=="missing_capsule"
    assert any(a["units"]==1 and a["result"].get("reason")=="missing_capsule" for a in r["actions"] if a["kind"]=="READ_CAPSULE")


def test_paid_gate_integrity_no_text_before_reserve(episode,tmp_path):
    public,env,gold,cfg=episode
    m=public["memories"][1]; idx=read_json(env/"index.json"); path=env/idx["capsule"][m["capsule_id"]]["path"]
    path.write_text("changed size",encoding="utf-8")
    j=Journal(tmp_path/"a.sqlite",{},2); gw=EvidenceGateway(env,public["snapshot_id"],j)
    r=gw.read_capsule(m["capsule_id"])
    assert r["reason"]=="invalid_length" and "text" not in r
    assert j.ledger()["spent_units"]==1; j.close()


def test_evaluation_absent_or_changed_does_not_change_repair(dataset,episode,tmp_path):
    public,env,gold,cfg=episode
    full=run_one(public,env,"tracepatch",16,cfg,tmp_path/"a.sqlite")
    root=dataset[0]; shutil.rmtree(root/"evaluation")
    absent=run_one(public,env,"tracepatch",16,cfg,tmp_path/"b.sqlite")
    assert logical_actions(full)==logical_actions(absent)
    write_json(root/"evaluation"/(gold["base_id"]+".json"),{"true_values":"nonsense","queries":[3,2,1]})
    modified=run_one(public,env,"tracepatch",16,cfg,tmp_path/"c.sqlite")
    assert logical_actions(full)==logical_actions(modified)
    repair=Path(__file__).resolve().parents[1]/"tracepatch"/"repair"
    assert not any("import evaluation" in p.read_text() or "from ..evaluation" in p.read_text() for p in repair.glob("*.py"))


def test_nested_masks_and_disjoint_splits(dataset):
    root,manifest,cfg=dataset
    bybase={}
    for item in manifest["entries"]: bybase.setdefault(item["base_id"],[]).append(item)
    entities=[]
    names=[]
    for entries in bybase.values():
        sets=[set(map(tuple,read_json(root/i["public"])["edges"])) for i in sorted(entries,key=lambda x:x["delta"])]
        assert all(b<=a for a,b in zip(sets,sets[1:])) and sets[0]!=sets[-1]
        entities.append(set(m["logical_id"] for m in read_json(root/entries[0]["public"])["memories"]))
        names.append({e for m in read_json(root/entries[0]["public"])["memories"] for e in m["entities"]})
    assert not entities[0]&entities[1]
    assert not names[0]&names[1]


@pytest.mark.parametrize("when",["committed","pending"])
def test_resume_matches_uninterrupted_exactly(episode,tmp_path,when):
    public,env,gold,cfg=episode
    full=run_one(public,env,"tracepatch",32,cfg,tmp_path/"full.sqlite")
    at=next(a["seq"] for a in full["actions"] if a["kind"]=="READ_SOURCE")
    opts={"crash_after" if when=="committed" else "crash_pending":at}
    with pytest.raises(InjectedCrash): run_one(public,env,"tracepatch",32,cfg,tmp_path/"resume.sqlite",**opts)
    resumed=run_one(public,env,"tracepatch",32,cfg,tmp_path/"resume.sqlite")
    assert full["records"]==resumed["records"]
    assert logical_actions(full)==logical_actions(resumed)
    assert logical_ledger(full)==logical_ledger(resumed)
    repeated=run_one(public,env,"tracepatch",32,cfg,tmp_path/"resume.sqlite")
    assert logical_actions(resumed)==logical_actions(repeated)


def test_cross_method_independent_cache(execute_episode):
    a=execute_episode("tracepatch",128); b=execute_episode("expanded_fifo",128)
    assert a["ledger"]["capsule_reads"]>0 and b["ledger"]["capsule_reads"]>0
    assert a["ledger"]["source_reads"]>0 and b["ledger"]["source_reads"]>0


@pytest.mark.parametrize("mode",["cycle","invalid_type","invalid_op","depth"])
def test_bad_recipes_return_unknown(episode,tmp_path,mode):
    public,env,gold,cfg=episode
    target=next(m for m in public["memories"] if "内存兼容" in m["text"])
    def mutate(cap):
        if mode=="cycle": cap.update(op="COPY",operands=[{"logical_id":target["logical_id"],"version_id":target["version_id"]}])
        if mode=="invalid_type": cap.update(op="GE",operands=[{"const":True},{"const":4}])
        if mode=="invalid_op": cap["op"]="__import__"
    if mode!="depth": rewrite_cap(env,target,mutate)
    if mode=="depth": cfg=dict(cfg,max_depth=0)
    r=run_one(public,env,"full_audit",None,cfg,tmp_path/"x.sqlite")
    assert r["results"][target["logical_id"]]["outcome"]=="UNKNOWN"
    assert r["ledger"]["reserved_units"]==0


def test_certificate_version_and_snapshot_invalidation(episode,tmp_path):
    public,env,gold,cfg=episode
    j=Journal(tmp_path/"x.sqlite",{},128); gw=EvidenceGateway(env,public["snapshot_id"],j)
    c=RepairContext(public,gw,j,"offline"); c.apply_root(); v=Verifier(c,Extractor("offline",j))
    target=public["memories"][2]["logical_id"]
    v.verify_and_rebuild(target); spent=j.ledger()["spent_units"]
    v.verify_and_rebuild(target); assert j.ledger()["spent_units"]==spent
    c.stamp="new_snapshot_semantics"; v.verify_and_rebuild(target)
    assert j.ledger()["spent_units"]==spent+1  # paid bytes cached; extraction must rerun
    c.memories[target]["version_id"]="different"; v.verify_and_rebuild(target)
    assert j.ledger()["spent_units"]==spent+2
    j.close()


def test_tfidf_empty_unicode_and_deterministic_ties(episode):
    public,env,gold,cfg=episode
    ms=[dict(m,text="",entities=[]) for m in public["memories"]]
    assert set(similarities(ms,ms[0],"",cfg["weights"]).values())=={0}
    ms[0]["text"]="ＡＢＣ"; ms[1]["text"]="abc"
    scores=similarities(ms,ms[0],"",cfg["weights"])
    assert scores[ms[0]["logical_id"]]==scores[ms[1]["logical_id"]]


@pytest.mark.parametrize("method",["no_semantic","no_usage","no_cost"])
def test_ablations_run_with_same_real_charging(execute_episode,method):
    state=execute_episode(method,8)
    assert 0<state["ledger"]["spent_units"]<=8
    assert state["ledger"]["reserved_units"]==0


def test_owner_scope_isolation(episode,tmp_path):
    public,env,gold,cfg=episode; public=deepcopy(public)
    other=next(m for m in public["memories"] if "内存兼容" in m["text"])
    other["owner_id"]="different_owner"
    state=run_one(public,env,"tracepatch",128,cfg,tmp_path/"owner.sqlite")
    assert other["logical_id"] not in state["results"]
    assert not any(a["kind"]=="STATE" and a["args"].get("logical_id")==other["logical_id"] for a in state["actions"])


def test_missing_source_charges_and_abstains(episode,tmp_path):
    public,env,gold,cfg=episode; m=public["memories"][2]
    index=read_json(env/"index.json"); cap=read_json(env/index["capsule"][m["capsule_id"]]["path"])
    key=cap["source"]["source_id"]+":"+cap["source"]["source_version"]
    (env/index["source"][key]["path"]).unlink()
    state=run_one(public,env,"full_audit",None,cfg,tmp_path/"missing.sqlite")
    assert state["results"][m["logical_id"]]["outcome"]=="UNKNOWN"
    assert any(a["kind"]=="READ_SOURCE" and a["units"]==1 and a["result"].get("reason")=="missing_source" for a in state["actions"])
