"""Synthetic motif DAGs. Independent SHA-derived RNG streams; gold kept separate."""
import hashlib
import random
from collections import Counter
from pathlib import Path
from ..common import canonical, digest, file_hash, write_json, GENERATOR_VERSION, typed_equal
from ..domain import execute, value_type


METHODS = ["root_only","graph_only","expanded_fifo","tracepatch","full_scan"]
WEIGHTS = {"entity":0.4,"text":0.6,"distance_decay":0.8,"semantic_risk":0.7,"usage_floor":0.25}


def rng(seed, split, ordinal, stream):
    return random.Random(int(digest([seed,split,ordinal,stream,"streams-1"]),16))


def build_episode(root_dir, seed, split, ordinal, cfg, demo=False):
    root_dir=Path(root_dir)
    ident=rng(seed,split,ordinal,"identifiers")
    opaque=lambda: "%024x" % ident.getrandbits(96)
    base_id=opaque(); snapshot=opaque(); owner=opaque(); scope=opaque()
    graph_rng=rng(seed,split,ordinal,"graph")
    n=cfg.get("nodes",[24,32]); count=graph_rng.randint(*n)
    # Latent popularity is generated without consulting fault position or graph.
    usage_rng=rng(seed,split,ordinal,"latent_usage")
    latent=[usage_rng.expovariate(1)+0.05 for _ in range(count)]
    root_index=0 if demo else rng(seed,split,ordinal,"root_choice").randrange(2)
    new=8 if demo else graph_rng.choice([8,9,10]); old=16 if demo else graph_rng.choice([16,20,24])
    threshold=12 if demo else graph_rng.randint(new+1,old)
    low=6 if demo else graph_rng.randint(4,new)
    product="星港" if demo else "虚构产品-"+opaque()[:6]
    dev="设备-"+opaque()[:6]
    specs=[]
    def fact(label,value,entities):
        specs.append({"kind":"fact","label":label,"value":value,"entities":entities}); return len(specs)-1
    def derived(label,op,args,entities,cache=False):
        specs.append({"kind":"cache" if cache else "derived","label":label,"op":op,"args":args,"entities":entities}); return len(specs)-1
    capacity=[]
    for i in range(2): capacity.append(fact(f"{dev} {'主机' if i==root_index else '备用机'}内存 GB",new if i==root_index else 16,[dev,"内存"]))
    pref=fact("用户喜欢回合制策略",True,["偏好","策略"])
    license_node=fact("云端游玩授权有效",True,["云端","授权"])
    disk=fact(f"{dev} 可用存储 GB",128,[dev,"存储"])
    region=fact("用户界面语言","zh-CN",["界面"])
    ref=lambda i:{"ref":i}
    const=lambda v:{"const":v}
    a=derived(f"{dev} 可以运行{product} A（内存兼容）","GE",[ref(root_index),const(threshold)],[dev,"内存",product])
    recommend=derived(f"推荐{product} A：设备要求符合","COPY",[ref(a)],[dev,product,"推荐"],True)
    derived(f"{product} A 策略探索资格","AND",[ref(a),ref(pref)],[dev,product,"策略"])
    derived(f"{product} A 推荐卡缓存","COPY",[ref(recommend)],[product,"推荐"],True)
    derived(f"{dev} 可以运行{product} B（低内存需求）","GE",[ref(root_index),const(low)],[dev,"内存",product])
    derived(f"{dev} 在轻量设备范围内","LE",[ref(root_index),const(old+8)],[dev,"内存"])
    branch=derived("云端独立支持：授权且偏好策略","AND",[ref(license_node),ref(pref)],["云端","策略"])
    derived(f"{product} A 可通过本地或云端体验","OR",[ref(a),ref(branch)],[dev,product,"云端"])
    derived(f"{product} 无关的存储兼容提示","GE",[ref(disk),const(64)],[product,dev,"内存"])
    depths=[0 if s["kind"]=="fact" else 1 for s in specs]
    for i,s in enumerate(specs):
        if s["kind"]!="fact": depths[i]=1+max([depths[x["ref"]] for x in s["args"] if "ref" in x] or [0])
    while len(specs)<count:
        i=len(specs)
        if i%3==0:
            fact(f"{product} 扩展属性 {i}",graph_rng.choice([True,False,2,7,"offline"]),[product,"属性"]); depths.append(0)
        else:
            candidates=[j for j in range(len(specs)) if depths[j]<cfg.get("max_depth",4)]
            p=graph_rng.choice(candidates)
            derived(f"{product} 派生记录 {i}：{specs[p]['label']}","COPY",[ref(p)],[product,dev] if graph_rng.random()<.5 else ["其他"],i%2==0)
            depths.append(depths[p]+1)
    ids=[opaque() for _ in specs]; versions=[opaque() for _ in specs]; capsule_ids=[opaque() for _ in specs]
    truths=[]; initials=[]; edges=[]
    for i,s in enumerate(specs):
        if s["kind"]=="fact":
            truths.append(s["value"]); initials.append(old if i==root_index else s["value"])
        else:
            vals=lambda known:[known[a["ref"]] if "ref" in a else a["const"] for a in s["args"]]
            truths.append(execute(s["op"],vals(truths))); initials.append(execute(s["op"],vals(initials)))
            edges.extend((ids[a["ref"]],ids[i]) for a in s["args"] if "ref" in a)
    descendants={ids[root_index]}
    for a_id,b_id in edges:
        if a_id in descendants: descendants.add(b_id)
    wrong=[i for i in range(count) if not typed_equal(initials[i],truths[i])]
    stable_desc=[i for i in range(count) if ids[i] in descendants and typed_equal(initials[i],truths[i])]
    unrelated=[i for i in range(count) if ids[i] not in descendants]
    if len(wrong)<4 or len(stable_desc)<3 or len(unrelated)<3 or max(depths)>cfg.get("max_depth",4): raise RuntimeError("generator_invariant_failed")
    past_rng=rng(seed,split,ordinal,"past_queries")
    past=past_rng.choices(range(count),weights=latent,k=count*8)
    past_counts=Counter(past)
    future_rng=rng(seed,split,ordinal,"future_queries")
    future_weights=list(reversed(latent)) if cfg.get("usage_shift") else latent
    future=future_rng.choices(range(count),weights=future_weights,k=count*5)
    missing_rng=rng(seed,split,ordinal,"capsule_loss")
    env=root_dir/"environment"/base_id
    index={"snapshot_id":snapshot,"capsule":{},"source":{}}
    def blob(resource,key,text,omit=False):
        path=env/resource/(digest(key)+".txt")
        body=text.encode("utf-8")
        index[resource][key]={"path":str(path.relative_to(env)).replace("\\","/"),"bytes":len(body),"sha256":hashlib.sha256(body).hexdigest()}
        if not omit:
            path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(body)
        return len(body)
    memories=[]
    for i,s in enumerate(specs):
        cap={"logical_id":ids[i],"kind":s["kind"],"owner_id":owner,"scope_id":scope,"input_trace":[],"generated_value":initials[i]}
        if s["kind"]=="fact":
            sid=opaque(); sv=opaque(); field="assertion"
            binding={"source_id":sid,"source_version":sv,"field_key":field,"type":value_type(truths[i]),"owner_id":owner,"scope_id":scope,"valid_from":0,"valid_to":None}
            cap["source"]=binding
            text=f"Fictional evidence / controlled template v1\nOwner: {owner}; Scope: {scope}\n{s['label']}\nFIELD "+canonical({"key":field,"type":value_type(truths[i]),"value":truths[i]})+"\n"
            blob("source",sid+":"+sv,text)
        else:
            cap.update(op=s["op"],operands=[{"logical_id":ids[x["ref"]],"version_id":versions[x["ref"]]} if "ref" in x else x for x in s["args"]])
            cap["input_trace"]=[initials[x["ref"]] if "ref" in x else x["const"] for x in s["args"]]
        loss=missing_rng.random()<cfg.get("capsule_loss",0)
        size=blob("capsule",capsule_ids[i],canonical(cap),loss and i!=root_index)
        memories.append({"logical_id":ids[i],"version_id":versions[i],"kind":s["kind"],"owner_id":owner,"scope_id":scope,"claim_key":"claim_"+opaque(),"value":initials[i],"text":s["label"]+" = "+canonical(initials[i]),"entities":[base_id+":"+e for e in s["entities"]],"created_step":i,"valid_from":0,"valid_to":None,"status":"ACTIVE","capsule_id":capsule_ids[i],"capsule_size_hint":2048*((size+2047)//2048),"last_used_step":max([j for j,x in enumerate(past) if x==i] or [-1]),"use_count":past_counts[i]})
    write_json(env/"index.json",index)
    event={"event_id":opaque(),"target_logical_id":ids[root_index],"target_version_id":versions[root_index],"owner_id":owner,"scope_id":scope,"kind":"CORRECTION","new_value":new,"effective_from":0,"effective_to":None,"issued_step":len(past)+count,"trusted_source_ref":"trusted-correction-"+opaque()}
    edge_rng=rng(seed,split,ordinal,"edge_masks")
    thresholds={edge:edge_rng.random() for edge in edges}
    if cfg.get("root_biased_mask"):
        thresholds={edge:(v*.5 if edge[0]==ids[root_index] else v) for edge,v in thresholds.items()}
    entries=[]
    for delta in cfg["deltas"]:
        observed=[list(e) for e in edges if thresholds[e]>=delta]
        if demo: observed=[e for e in observed if e!=[ids[a],ids[recommend]]]
        if cfg.get("spurious_edges"):
            fake_rng=rng(seed,split,ordinal,"spurious_edges")
            for _ in range(cfg["spurious_edges"]):
                x,y=sorted(fake_rng.sample(range(count),2))
                if [ids[x],ids[y]] not in observed: observed.append([ids[x],ids[y]])
        variant=digest([base_id,delta])[:24]
        public={"base_id":base_id,"variant_id":variant,"snapshot_id":snapshot,"memories":memories,"edges":observed,"correction":event,"pre_correction_usage":[{"logical_id":ids[x],"step":j} for j,x in enumerate(past)]}
        path=root_dir/"public"/(variant+".json"); write_json(path,public)
        entries.append({"base_id":base_id,"variant_id":variant,"split":split,"delta":delta,"public":"public/"+variant+".json","environment":"environment/"+base_id})
    gold={"base_id":base_id,"root":ids[root_index],"true_values":dict(zip(ids,truths)),"initial_values":dict(zip(ids,initials)),"true_edges":edges,"wrong_initial":[ids[i] for i in wrong],"unchanged_descendants":[ids[i] for i in stable_desc],"descendants":sorted(descendants),"queries":{},"generation":{"seed":seed,"split":split,"ordinal":ordinal,"attempts":1,"root_index":root_index,"latent_usage":latent,"streams":"streams-1","parameters":cfg}}
    for label,queries in [("usage",future),("uniform",range(count))]:
        gold["queries"][label]=[{"id":opaque(),"logical_id":ids[i],"claim_key":memories[i]["claim_key"],"owner_id":owner,"scope_id":scope,"at":1,"answer":truths[i]} for i in queries]
    write_json(root_dir/"evaluation"/(base_id+".json"),gold)
    return entries


def build_dataset(config,out,demo=False):
    out=Path(out)
    if (out/"manifest.json").exists(): raise ValueError("dataset_exists_use_new_directory")
    entries=[]
    for seed in config["seeds"]:
        for split,n in (("dev",config["dev_scenarios"]),("test",config["test_scenarios"])):
            for ordinal in range(n): entries.extend(build_episode(out,seed,split,ordinal,config,demo))
    files={str(p.relative_to(out)).replace("\\","/"):file_hash(p) for folder in ("public","environment") for p in sorted((out/folder).rglob("*")) if p.is_file()}
    # Generation parameters and future labels stay in evaluation; manifest has hashes only.
    manifest={"generator_version":GENERATOR_VERSION,"streams_version":"streams-1","entries":entries,"files":files,"content_hash":digest(files),"generation_config_hash":digest(config)}
    write_json(out/"manifest.json",manifest)
    return manifest
