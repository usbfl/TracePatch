"""Five schedulers share exactly one candidate builder and verifier."""
import math
import unicodedata
from collections import Counter
from ..storage import BudgetExhausted


def similarities(memories, root, correction_text, weights):
    def grams(s):
        s = unicodedata.normalize("NFKC",s).casefold()
        return Counter(s[i:i+3] for i in range(max(0,len(s)-2)))
    docs = [grams(m["text"]) for m in memories]
    query = grams(root["text"]+" "+correction_text)
    all_docs = docs+[query]
    df = Counter(g for doc in all_docs for g in doc)
    idf = {g:math.log((1+len(all_docs))/(1+n))+1 for g,n in df.items()}
    def vector(doc):
        v = {g:n*idf[g] for g,n in doc.items()}
        norm = math.sqrt(sum(x*x for x in v.values()))
        return {g:x/norm for g,x in v.items()} if norm else {}
    q = vector(query); out = {}
    for m,doc in zip(memories,docs):
        v=vector(doc); entities=set(m["entities"]); roots=set(root["entities"])
        overlap=len(entities&roots)/len(entities|roots) if entities|roots else 0
        out[m["logical_id"]] = weights["entity"]*overlap+weights["text"]*sum(x*q.get(g,0) for g,x in v.items())
    return out


class Scheduler:
    def __init__(self, context, verifier, method, config):
        self.c,self.verifier,self.method,self.cfg = context,verifier,method,config
        self.pool,self.semantic_pool = set(),set()
        self.distance,self.sim = {},{}

    def expand(self):
        self.distance = self.c.distance()
        self.pool.update(self.distance)
        for node in sorted(self.distance):
            if node not in self.c.certificates and node not in self.c.attempted:
                self.c.quarantine(node,"visible_dependency")

    def run(self):
        c = self.c
        c.apply_root()
        if self.method == "root_only": return "completed"
        if self.method == "all_quarantine":
            for node in sorted(c.memories):
                if node != c.root and c.eligible(node): c.quarantine(node,"diagnostic_all_quarantine")
            return "completed"
        valid = [m for m in c.initial if m["logical_id"]!=c.root and c.eligible(m["logical_id"])]
        c.on_edges = self.expand
        self.expand()
        initial_obs = set(self.distance)
        if self.method in {"tracepatch","expanded_fifo","no_usage","no_cost"}:
            def propose():
                initial_root=next(m for m in c.initial if m["logical_id"]==c.root)
                sim = similarities(c.initial,initial_root,"Trusted correction: "+str(c.event["new_value"]),self.cfg["weights"])
                ordered = sorted((m for m in valid if m["logical_id"] not in initial_obs and m["logical_id"] not in c.certificates),key=lambda m:(-sim[m["logical_id"]],m["created_step"],m["logical_id"]))
                return {"scores":sim,"semantic_pool":[m["logical_id"] for m in ordered[:self.cfg["semantic_k"]]],"records":len(c.initial)}
            proposed = c.journal.atomic("SELECT",{"stage":"initial_semantic","method":self.method},0,propose)
            self.sim = proposed["scores"]; self.semantic_pool=set(proposed["semantic_pool"])
            self.pool.update(self.semantic_pool)
        if self.method in {"full_scan","full_audit"}: self.pool.update(m["logical_id"] for m in valid)
        focus = {n:i for i,n in enumerate(self.cfg.get("focus_targets",[])) if n in c.memories and c.eligible(n)}
        if self.method == "tracepatch":
            self.pool.update(focus)
        c.journal.atomic("CANDIDATES",{"initial_observed":sorted(initial_obs),"semantic":sorted(self.semantic_pool),"initial_candidates":sorted(self.pool)})
        max_count = max((m["use_count"] for m in c.initial),default=0)
        counts = {m["logical_id"]:m["use_count"] for m in c.initial}
        def rank(node):
            m=c.memories[node]
            if self.method == "graph_only": return (self.distance.get(node,float("inf")),m["created_step"],node)
            if self.method in {"full_scan","full_audit","expanded_fifo"}: return (m["created_step"],node)
            if self.method == "tracepatch" and node in focus:
                return (-1000+focus[node],m["created_step"],node)
            w=self.cfg["weights"]
            g=w["distance_decay"]**(self.distance[node]-1) if node in self.distance else 0
            r=max(g,w["semantic_risk"]*self.sim.get(node,0))
            u=math.log1p(counts[node])/math.log1p(max_count) if max_count else 1
            if self.method == "no_usage": u=1
            cost=max(1,math.ceil((m["capsule_size_hint"] or 1)/2048))+1+sum(1 for a,b in c.graph if b==node and a not in c.certificates)
            if self.method == "no_cost": cost=1
            return (-r*(w["usage_floor"]+(1-w["usage_floor"])*u)/cost,m["created_step"],node)
        while True:
            remaining = [n for n in self.pool if n not in c.certificates and n not in c.attempted]
            if not remaining: return "completed"
            def select():
                node=min(remaining,key=rank)
                return {"logical_id":node,"rank":rank(node),"records":len(remaining)}
            choice=c.journal.atomic("SELECT",{"stage":"next","remaining":sorted(remaining)},0,select)
            try: self.verifier.verify_and_rebuild(choice["logical_id"])
            except BudgetExhausted: return "budget_exhausted"
