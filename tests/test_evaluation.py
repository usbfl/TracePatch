from copy import deepcopy
from pathlib import Path
import pytest
from tracepatch.evaluation import score_state, aggregate
from tracepatch.experiment import run_matrix,freeze_protocol,verify_frozen
from tracepatch.common import read_json,write_json
from tracepatch.report import table


def test_hand_calculated_denominators_and_new_errors(episode):
    public,env,gold,cfg=episode
    ids=[m["logical_id"] for m in public["memories"][:3]]
    records=deepcopy(public["memories"][:3])
    for m in records: m["value"]=1
    gold={"root":ids[0],"true_values":{ids[0]:2,ids[1]:2,ids[2]:1},"initial_values":{ids[0]:1,ids[1]:1,ids[2]:1},"wrong_initial":ids[:2],"queries":{"uniform":[dict(id=str(i),logical_id=m["logical_id"],owner_id=m["owner_id"],scope_id=m["scope_id"],claim_key=m["claim_key"],at=1,answer=2 if i<2 else 1) for i,m in enumerate(records)]}}
    records[0]["value"]=2
    metrics,rows=score_state(records,gold,"uniform")
    assert metrics["overall_accuracy"]==2/3 and metrics["coverage"]==1
    assert metrics["stale_error_reuse"]==1 and metrics["original_error_residual"]==.5
    records[1]["value"]=3
    metrics,_=score_state(records,gold,"uniform")
    assert metrics["stale_error_reuse"]==0 and metrics["global_wrong_active"]==1/3
    records[2]["value"]=0
    metrics,_=score_state(records,gold,"uniform")
    assert metrics["new_errors"]==1
    for m in records: m["status"]="QUARANTINED"
    metrics,_=score_state(records,gold,"uniform")
    assert metrics["coverage"]==metrics["overall_accuracy"]==0 and metrics["selective_accuracy"] is None
    assert metrics["benign_unavailability"]==1


def test_same_value_successor_counts_preserved(execute_episode,episode):
    r=execute_episode("full_audit",None)
    m,_=score_state(r["records"],episode[2],"uniform")
    assert m["benign_unavailability"]==0 and m["overall_accuracy"]==1
    q=execute_episode("all_quarantine",0)
    m,_=score_state(q["records"],episode[2],"uniform")
    assert m["coverage"]<.1 and m["benign_unavailability"]==1


def test_bootstrap_pairs_by_base_and_shared_samples():
    rows=[]
    for base,v in [('x',.3),('y',.9)]:
        for method,offset in [('tracepatch',0),('expanded_fifo',-.1)]:
            for delta in [0,.5]: rows.append(dict(base_id=base,provider='offline',query_set='uniform',delta=delta,budget=8,method=method,status='completed',overall_accuracy=v+offset))
    summary,paired,meta=aggregate(rows,100)
    assert meta["base_scenarios"]==2 and len(meta["samples"][0])==2
    assert all(abs(r["mean_difference"]-.1)<1e-9 for r in paired if r["metric"]=="overall_accuracy")
    assert aggregate(list(reversed(rows)),100)[2]["shared_sample_indices_hash"]==meta["shared_sample_indices_hash"]


def test_freeze_and_state_config_tampering(dataset,tmp_path):
    data,manifest,cfg=dataset; cfg=dict(cfg,methods=['root_only'],budgets=[0])
    run=tmp_path/'run'; lock=tmp_path/'protocol.json'
    run_matrix(data,run,'dev',cfg); freeze_protocol(run,lock)
    test=tmp_path/'test'; run_matrix(data,test,'test',protocol=lock); verify_frozen(test)
    path=test/'config_snapshot.json'; saved=read_json(path); changed=dict(saved,semantic_k=999); write_json(path,changed)
    with pytest.raises(ValueError,match='config'): verify_frozen(test)
    write_json(path,saved)
    state_path=next((test/'states').glob('*.json')); s=read_json(state_path); s['records'][0]['value']=999; write_json(state_path,s)
    with pytest.raises(ValueError,match='hash'): verify_frozen(test)


def test_html_escapes_untrusted_text():
    rendered=table([{'x':'<script>alert("x")</script>'}],[('x','x')])
    assert '<script>' not in rendered and '&lt;script&gt;' in rendered
