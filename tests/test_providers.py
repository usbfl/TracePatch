import json
import os
import pytest
from tracepatch.common import digest
from tracepatch.storage import Journal, InjectedCrash
from tracepatch.verify.providers import Extractor, ApiQuota, offline_extract

TEXT='FIELD {"key":"ram","type":"int","value":8}\n'
BIND={"field_key":"ram","type":"int","source_id":"opaque","source_version":"v1","scope_id":"s"}
MODEL={"base_url":"https://example.invalid/v1","model":"configured-test-model","temperature":0}


def response(value=8,quote=TEXT.strip()):
    content=dict(outcome="KNOWN",value=value,source_id="opaque",source_version="v1",quote=quote,reason="")
    return {"status":200,"sent":True,"body":{"choices":[{"message":{"content":json.dumps(content)}}],"usage":{"prompt_tokens":12,"completion_tokens":8}},"usage":{"prompt_tokens":12,"completion_tokens":8}}


def test_offline_extract_reads_text_not_ids():
    assert offline_extract(TEXT,BIND)["value"]==8
    assert offline_extract(TEXT.replace('8','12'),BIND)["value"]==12
    assert offline_extract("nothing",BIND)["outcome"]=="UNKNOWN"
    assert offline_extract(TEXT+TEXT,BIND)["reason"]=="conflicting_evidence"


def test_offline_never_calls_network_even_with_key(tmp_path,monkeypatch):
    monkeypatch.setenv("TRACEPATCH_API_KEY","unit-test-not-a-real-key")
    def fail(*args): raise AssertionError("network used")
    monkeypatch.setattr("urllib.request.build_opener",fail)
    j=Journal(tmp_path/"a.sqlite",{},8)
    assert Extractor("offline",j,transport=fail).extract(TEXT,BIND)["value"]==8
    assert j.ledger()["model_requests"]==0
    with pytest.raises(ValueError,match="allow_network"): Extractor("live",j,MODEL)
    j.close()


@pytest.mark.parametrize("status,expected",[(400,1),(401,1),(429,2),(500,2),(503,2)])
def test_http_retry_bounds_and_accounting(tmp_path,status,expected):
    j=Journal(tmp_path/"a.sqlite",{},8); q=ApiQuota(tmp_path/"quota.sqlite",32); calls=[]
    def transport(*args): calls.append(1); return {"status":status,"sent":True}
    p=Extractor("live",j,MODEL,True,q,transport=transport,run_id="unit-test")
    assert p.extract(TEXT,BIND)["outcome"]=="UNKNOWN"
    assert len(calls)==expected
    assert j.ledger()["model_requests"]==expected and j.ledger()["retry_requests"]==expected-1
    assert j.ledger()["input_tokens"] is None
    j.close(); q.db.close()


def test_uncertain_never_retried(tmp_path):
    j=Journal(tmp_path/"a.sqlite",{},8); q=ApiQuota(tmp_path/"quota.sqlite",32); calls=[]
    def transport(*args): calls.append(1); return {"reason":"uncertain","sent":True}
    p=Extractor("live",j,MODEL,True,q,transport=transport,run_id="unit-test")
    assert p.extract(TEXT,BIND)["reason"]=="uncertain" and len(calls)==1
    j.close(); q.db.close()


def test_pending_network_resume_becomes_uncertain(tmp_path):
    # Simulate an interruption after durable reservation, before confirmation.
    j=Journal(tmp_path/"a.sqlite",{},8,crash_pending=3); q=ApiQuota(tmp_path/"quota.sqlite",32)
    p=Extractor("live",j,MODEL,True,q,transport=lambda *a:response(),run_id="unit-test")
    with pytest.raises(InjectedCrash): p.extract(TEXT,BIND)
    j.close()
    j=Journal(tmp_path/"a.sqlite",{},8)
    def fail(*args): raise AssertionError("uncertain request resent")
    p=Extractor("live",j,MODEL,True,q,transport=fail,run_id="unit-test")
    assert p.extract(TEXT,BIND)["reason"]=="uncertain"
    assert j.ledger()["model_requests"]==1
    j.close(); q.db.close()


def test_global_quota_and_length_limits(tmp_path):
    q=ApiQuota(tmp_path/"quota.sqlite",1); calls=[]
    for n in range(2):
        j=Journal(tmp_path/f'{n}.sqlite',{},8)
        def transport(*args): calls.append(1); return response()
        p=Extractor("live",j,MODEL,True,q,transport=transport,run_id=str(n))
        result=p.extract(TEXT,BIND)
        assert result["outcome"]==("KNOWN" if n==0 else "UNKNOWN")
        j.close()
    assert len(calls)==1
    j=Journal(tmp_path/"long.sqlite",{},8)
    p=Extractor("live",j,dict(MODEL,max_input_chars=1),True,q,transport=lambda *a:pytest.fail("network"))
    assert p.extract(TEXT,BIND)["reason"]=="context_limit"
    j.close(); q.db.close()


@pytest.mark.parametrize("r",[response(True),response(8,"not in source"),{"status":200,"body":{"choices":[{"message":{"content":"not-json"}}]}}])
def test_invalid_model_output_fails_closed(r):
    assert Extractor.validate(r,TEXT,BIND)["reason"]=="invalid_model_output"


def test_recorded_response_replay_semantic_hash_not_path(tmp_path):
    j=Journal(tmp_path/"live.sqlite",{},8); q=ApiQuota(tmp_path/"quota.sqlite",32)
    live=Extractor("live",j,MODEL,True,q,transport=lambda *a:response(),run_id="simulated-http-test")
    original=live.extract(TEXT,BIND)
    action=next(a for a in j.actions() if a["kind"]=="MODEL_REQUEST")
    record=dict(action["args"],response=action["result"]); records={record["request_hash"]:record}
    j.close()
    j=Journal(tmp_path/"other-directory.sqlite",{},8)
    replay=Extractor("replay",j,MODEL,replay=records)
    assert replay.extract(TEXT,BIND)==original and j.ledger()["model_requests"]==0
    j.close()
    j=Journal(tmp_path/"bad.sqlite",{},8)
    with pytest.raises(ValueError,match="replay_provenance"):
        Extractor("replay",j,dict(MODEL,temperature=1),replay=records).extract(TEXT,BIND)
    j.close(); q.db.close()
