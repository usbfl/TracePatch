from copy import deepcopy
import pytest
from tracepatch.domain import execute, value_type, TemporalStore, QueryReader, validate_record


@pytest.mark.parametrize("op,args,expected",[("GE",[8,12],False),("GE",[8,6],True),("AND",[True,None],None),("AND",[False,None],False),("OR",[False,None],None),("OR",[True,None],True),("NOT",[None],None),("COPY",["abc"],"abc"),("EQ",[3,3],True),("LE",[3,4],True)])
def test_rules(op,args,expected): assert execute(op,args) is expected or execute(op,args)==expected


@pytest.mark.parametrize("op,args",[("GE",[True,1]),("EQ",[True,1]),("AND",[1,True]),("unknown",[1]),("COPY",[1,2]),("OR",[True]*5)])
def test_reject_types_and_rules(op,args):
    with pytest.raises(ValueError): execute(op,args)


def test_complete_support_branches():
    assert execute("OR",[execute("AND",[False,True]),execute("AND",[True,None])]) is None
    assert execute("OR",[execute("AND",[None,True]),execute("AND",[True,True])]) is True


def test_temporal_update_correction_context_and_idempotency(episode):
    public,*_=episode
    root=next(m for m in public["memories"] if m["logical_id"]==public["correction"]["target_logical_id"])
    event=deepcopy(public["correction"])
    s=TemporalStore([root]); event.update(kind="UPDATE",effective_from=10)
    s.apply(event); before=len(s.records); s.apply(event); assert len(s.records)==before
    q=QueryReader(s.records)
    args=(root["logical_id"],root["owner_id"],root["scope_id"])
    assert q.query(*args,5)["value"]==16 and q.query(*args,10)["value"]==8
    s=TemporalStore([root]); event=deepcopy(public["correction"]); event.update(effective_from=3,effective_to=7)
    s.apply(event); q=QueryReader(s.records)
    assert [q.query(*args,t)["value"] for t in [0,3,6,7]]==[16,8,8,16]
    s=TemporalStore([root]); event=deepcopy(public["correction"]); event.update(kind="CONTEXTUAL_ASSERTION",scope_id="different")
    s.apply(event); q=QueryReader(s.records)
    assert q.query(*args,1)["value"]==16
    assert q.query(root["logical_id"],root["owner_id"],"different",1)["value"]==8


def test_public_schema_and_oversize(episode):
    public,*_=episode
    for m in public["memories"]: validate_record(m)
    m=dict(public["memories"][0],true_value=8)
    with pytest.raises(ValueError,match="public_schema"): validate_record(m)
    m=dict(public["memories"][0],text="x"*20000)
    with pytest.raises(ValueError,match="oversized"): validate_record(m)
    with pytest.raises(ValueError): value_type(1.2)
