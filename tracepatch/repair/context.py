from copy import deepcopy
from ..common import digest, RULE_VERSION, canonical
from ..domain import compatible, validate_record, value_type


class RepairContext:
    """Public view + observed graph + paid gateway + ledger + past usage only."""
    def __init__(self, public, gateway, journal, mode):
        self.initial = deepcopy(public["memories"])
        for m in self.initial: validate_record(m)
        self.memories = {m["logical_id"]:deepcopy(m) for m in self.initial}
        self.history = {m["logical_id"]:[deepcopy(m)] for m in self.initial}
        self.event = deepcopy(public["correction"])
        if self.event["kind"] != "CORRECTION": raise ValueError("main_experiment_requires_correction")
        self.snapshot = public["snapshot_id"]
        self.graph = set(tuple(e) for e in public["edges"])
        self.gateway,self.journal,self.mode = gateway,journal,mode
        self.certificates,self.attempted,self.results = {},set(),{}
        self.certified_versions,self.attempt_stamps = {},{}
        self.on_edges = lambda: None
        self.stamp = digest([self.snapshot,self.event,RULE_VERSION,mode])
        self.root = self.event["target_logical_id"]
        journal.atomic("STATE",{"logical_id":"initial_snapshot","records":self.initial,"reason":"initial_snapshot"})
        journal.atomic("INITIAL_GRAPH",{"edges":sorted(self.graph)})

    def eligible(self, node): return node in self.memories and compatible(self.memories[node],self.event)

    def quarantine(self, node, reason):
        m = self.memories[node]
        if m["status"] == "QUARANTINED" and m.get("reason") == reason: return
        m = dict(m,status="QUARANTINED",reason=reason)
        self.memories[node] = m
        self.history[node][-1] = m
        self.journal.atomic("STATE", {"logical_id":node,"records":[m],"reason":reason})

    def publish(self,node,value,certificate,reason):
        old = dict(self.memories[node],status="SUPERSEDED")
        new = dict(old,version_id=digest([node,self.stamp,value,certificate])[:24],value=value,text=old["text"].rsplit(" = ",1)[0]+" = "+canonical(value),status="ACTIVE",reason=reason,certificate=certificate)
        self.history[node][-1] = old
        self.history[node].append(new)
        self.memories[node] = new
        self.certificates[node] = certificate
        self.certified_versions[node] = new["version_id"]
        self.journal.atomic("STATE", {"logical_id":node,"records":[old,new],"certificate":certificate,"reason":reason})

    def apply_root(self):
        root = self.memories[self.root]
        if root["version_id"] != self.event["target_version_id"] or not self.eligible(self.root): raise ValueError("root_target_mismatch")
        if value_type(root["value"]) != value_type(self.event["new_value"]): raise ValueError("correction_type_mismatch")
        cert = {"stamp":self.stamp,"snapshot_id":self.snapshot,"event_id":self.event["event_id"],"rules":RULE_VERSION,"mode":self.mode,"leaves":[{"event_id":self.event["event_id"],"trusted_source_ref":self.event["trusted_source_ref"]}],"rules_used":[]}
        self.publish(self.root,self.event["new_value"],cert,"trusted_correction")

    def add_edges(self, parents, child, read_action_id):
        changed = False
        for parent in parents:
            if (parent,child) not in self.graph:
                self.graph.add((parent,child)); changed = True
                self.journal.atomic("EDGE", {"parent":parent,"child":child,"read_action_id":read_action_id})
        if changed: self.on_edges()

    def distance(self):
        def traverse():
            distances, queue, visits = {self.root:0},[self.root],0
            adjacency = {}
            for a,b in sorted(self.graph): adjacency.setdefault(a,[]).append(b)
            while queue:
                a = queue.pop(0); visits += 1
                for b in adjacency.get(a,[]):
                    if self.eligible(b) and b not in distances:
                        distances[b] = distances[a]+1; queue.append(b)
            distances.pop(self.root,None)
            return {"visits":visits,"distances":distances}
        return self.journal.atomic("GRAPH",{"graph_hash":digest(sorted(self.graph))},0,traverse)["distances"]

    def records(self):
        return [m for node in sorted(self.history) for m in self.history[node]]
