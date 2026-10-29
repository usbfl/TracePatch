"""Shared recursive verifier: no evaluation imports, no hidden DAG access."""
import json
from ..common import digest, typed_equal, RULE_VERSION
from ..domain import execute, value_type
from ..storage import BudgetExhausted


class Verifier:
    def __init__(self, context, extractor, max_depth=4):
        self.c,self.extractor,self.max_depth = context,extractor,max_depth
        self.audit_offsets = {}

    def verify_and_rebuild(self, node, stack=()):
        c = self.c
        if node in stack: return {"outcome":"UNKNOWN","reason":"cycle","new_value":None,"support":[],"rules":[]}
        if len(stack)>self.max_depth: return {"outcome":"UNKNOWN","reason":"depth_limit","new_value":None,"support":[],"rules":[]}
        if not c.eligible(node): return {"outcome":"UNKNOWN","reason":"incompatible_scope_time","new_value":None,"support":[],"rules":[]}
        if node in c.certificates:
            cert = c.certificates[node]
            if cert["stamp"] == c.stamp and c.memories[node]["status"] == "ACTIVE" and c.certified_versions.get(node) == c.memories[node]["version_id"]:
                c.journal.atomic("CACHE_HIT",{"resource":"certificate","key":node,"stamp":c.stamp})
                return {"outcome":"SUPPORTED_SAME","new_value":c.memories[node]["value"],"support":cert["leaves"],"rules":cert["rules_used"]}
        if node in c.attempted and c.results[node]["outcome"] == "UNKNOWN" and c.attempt_stamps.get(node) == (c.stamp,c.memories[node]["version_id"]):
            c.journal.atomic("CACHE_HIT",{"resource":"unknown","key":node,"stamp":c.stamp})
            return c.results[node]
        self.audit_offsets[node]=c.journal.cursor
        c.journal.atomic("AUDIT_START",{"logical_id":node,"recursive":bool(stack)})
        before = c.memories[node]["value"]
        c.quarantine(node,"audit_pending")
        try:
            result = self._evaluate(node,stack)
        except BudgetExhausted:
            self._finish(node,before,{"outcome":"UNKNOWN","reason":"budget_exhausted","new_value":None,"support":[],"rules":[]})
            raise
        except (ValueError,KeyError,TypeError,UnicodeError) as exc:
            reason = str(exc) if isinstance(exc,ValueError) and str(exc) in {"invalid_type","invalid_operation","invalid_capsule","version_binding_mismatch","oversized_value"} else "invalid_capsule"
            result = {"outcome":"UNKNOWN","reason":reason,"new_value":None,"support":[],"rules":[]}
        return self._finish(node,before,result)

    def _finish(self,node,before,r):
        c = self.c
        if r["new_value"] is not None:
            value_type(r["new_value"])
            r["outcome"] = "SUPPORTED_SAME" if typed_equal(before,r["new_value"]) else "REPLACED"
            cert = {"stamp":c.stamp,"snapshot_id":c.snapshot,"event_id":c.event["event_id"],"rules":RULE_VERSION,"mode":c.mode,"leaves":r["support"],"rules_used":r["rules"]}
            c.publish(node,r["new_value"],cert,r["outcome"])
        else:
            r["outcome"] = "UNKNOWN"
            c.quarantine(node,r.get("reason","missing_evidence"))
        r["old_value"] = before
        offset=self.audit_offsets[node]
        events=c.journal.actions()[offset:c.journal.cursor]
        r["work_units"]=sum(e["units"] for e in events if e["status"]=="committed")
        r["read_events"]=[e["action_id"] for e in events if e["kind"] in {"READ_CAPSULE","READ_SOURCE"}]
        r["recovered_edges"]=[e["result"] for e in events if e["kind"]=="EDGE"]
        r["certificate"]=c.certificates.get(node) if r["outcome"]!="UNKNOWN" else None
        c.attempted.add(node); c.results[node] = r
        c.attempt_stamps[node] = (c.stamp,c.memories[node]["version_id"])
        c.journal.atomic("AUDIT_END",dict(r,logical_id=node))
        return r

    def _evaluate(self,node,stack):
        c = self.c
        raw = c.gateway.read_capsule(c.memories[node]["capsule_id"])
        unknown = lambda reason: {"outcome":"UNKNOWN","reason":reason,"new_value":None,"support":[],"rules":[]}
        if raw.get("reason"): return unknown(raw["reason"])
        cap = json.loads(raw["text"])
        if cap["logical_id"] != node or cap["owner_id"] != c.event["owner_id"] or cap["scope_id"] != c.event["scope_id"]: raise ValueError("invalid_capsule")
        if cap["kind"] == "fact":
            binding = cap["source"]
            m=c.memories[node]
            if binding["owner_id"]!=m["owner_id"] or binding["scope_id"]!=m["scope_id"] or binding["valid_from"]>m["valid_from"] or (binding["valid_to"] is not None and (m["valid_to"] is None or binding["valid_to"]<m["valid_to"])):
                return unknown("incompatible_scope_time")
            source = c.gateway.read_source(binding["source_id"],binding["source_version"],binding["field_key"],c.snapshot)
            if source.get("reason"): return unknown(source["reason"])
            r = self.extractor.extract(source["text"],binding)
            if r["outcome"] == "UNKNOWN": return unknown(r.get("reason","missing_evidence"))
            return {"new_value":r["value"],"support":[dict(binding,quote=r["quote"],evidence_hash=digest(source["text"]))],"rules":[]}
        op,args = cap["op"],cap["operands"]
        if not isinstance(args,list) or len(args)>4: raise ValueError("invalid_capsule")
        execute(op,[None]*len(args))  # validate operator and arity before reading inputs
        parents = []
        for a in args:
            if set(a) == {"const"}: value_type(a["const"])
            elif set(a) == {"logical_id","version_id"}:
                p = a["logical_id"]
                if p not in c.history or a["version_id"] != c.history[p][0]["version_id"]: raise ValueError("version_binding_mismatch")
                parents.append(p)
            else: raise ValueError("invalid_capsule")
        c.add_edges(parents,node,raw["read_action_id"])
        vals,support,used_rules,reasons = [],[],[],[]
        for a in args:
            if "const" in a: r = {"new_value":a["const"],"support":[],"rules":[]}
            else: r = self.verify_and_rebuild(a["logical_id"],stack+(node,))
            vals.append(r["new_value"])
            support.extend(r["support"]); used_rules.extend(r["rules"])
            if r.get("reason"): reasons.append(r["reason"])
            if (op == "AND" and r["new_value"] is False) or (op == "OR" and r["new_value"] is True):
                # A single decisive child is a complete support branch.
                support,used_rules = list(r["support"]),list(r["rules"])
                break
        padded = vals+[None]*(len(args)-len(vals))
        def compute():
            try: return {"value":execute(op,padded)}
            except ValueError as exc: return {"value":None,"reason":str(exc)}
        result = c.journal.atomic("RULE",{"logical_id":node,"op":op,"values":padded,"rules":RULE_VERSION},1,compute)
        if result.get("reason"): return unknown(result["reason"])
        if result["value"] is None: return unknown(reasons[0] if reasons else "missing_evidence")
        unique = lambda xs: list({digest(x):x for x in xs}.values())
        return {"new_value":result["value"],"support":unique(support),"rules":unique(used_rules+[{"logical_id":node,"capsule_hash":digest(raw["text"]),"read_action_id":raw["read_action_id"]}])}
