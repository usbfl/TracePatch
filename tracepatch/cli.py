import argparse
import json
import os
import sys
from pathlib import Path
from .common import write_json
from .data import build_dataset
from .experiment import load_config, run_matrix, freeze_protocol
from .evaluation import evaluate
from .report import report


def main():
    parser=argparse.ArgumentParser(prog="tracepatch",description="Offline structured memory repair research demo")
    subs=parser.add_subparsers(dest="command",required=True)
    data=subs.add_parser("data"); ds=data.add_subparsers(dest="data_command",required=True)
    build=ds.add_parser("build"); build.add_argument("--config",required=True); build.add_argument("--out",required=True)
    demo=subs.add_parser("demo"); demo.add_argument("--out",default="runs/demo"); demo.add_argument("--provider",choices=["offline"],default="offline")
    run=subs.add_parser("run"); run.add_argument("--config"); run.add_argument("--protocol"); run.add_argument("--data"); run.add_argument("--split",choices=["dev","test"],default="dev"); run.add_argument("--out",required=True); run.add_argument("--provider",choices=["offline","live","replay"],default="offline"); run.add_argument("--allow-network",action="store_true"); run.add_argument("--resume",action="store_true"); run.add_argument("--replay-from")
    freeze=subs.add_parser("freeze-protocol"); freeze.add_argument("--run",required=True); freeze.add_argument("--out",required=True)
    ev=subs.add_parser("evaluate"); ev.add_argument("--run",required=True); ev.add_argument("--gold",required=True)
    rep=subs.add_parser("report"); rep.add_argument("--run",required=True)
    vdemo=subs.add_parser("v2-demo",help="Offline memory-to-plan-to-writeback demonstration")
    vdemo.add_argument("--out",default="runs/v2_demo_local"); vdemo.add_argument("--resume",action="store_true")
    vsmoke=subs.add_parser("v2-smoke",help="Frozen-prefix offline workflow benchmark")
    vsmoke.add_argument("--out",default="runs/v2_smoke_local"); vsmoke.add_argument("--config",default="configs/workflow_smoke.json"); vsmoke.add_argument("--resume",action="store_true")
    veval=subs.add_parser("v2-evaluate"); veval.add_argument("--run",required=True); veval.add_argument("--gold",required=True)
    vrep=subs.add_parser("v2-report"); vrep.add_argument("--run",required=True)
    args=parser.parse_args()
    try:
        if args.command in {"v2-demo","v2-smoke"}:
            from .workflow.experiment import run_suite
            from .common import read_json
            result=run_suite(args.out,read_json(args.config) if args.command=="v2-smoke" else None,
                             demo=args.command=="v2-demo",resume=args.resume,progress=lambda s: print(s,flush=True))
            print(json.dumps(result,ensure_ascii=False,indent=2))
            if result["failed"]: return sys.exit(1)
        elif args.command=="v2-evaluate":
            from .workflow.evaluate import evaluate_bundle
            print(json.dumps(evaluate_bundle(args.run,args.gold),ensure_ascii=False,indent=2))
        elif args.command=="v2-report":
            from .workflow.report import report as v2_report
            print(v2_report(args.run).resolve())
        elif args.command=="data":
            result=build_dataset(load_config(args.config),args.out); print("Built",len(result["entries"]),"public snapshots")
        elif args.command=="demo":
            out=Path(args.out)
            from .data import METHODS,WEIGHTS
            config={"name":"demo","seeds":[101],"dev_scenarios":1,"test_scenarios":0,"nodes":[24,24],"deltas":[0],"budgets":[8,128],"capsule_loss":0,"semantic_k":16,"max_depth":4,"methods":METHODS,"weights":WEIGHTS,"max_api_attempts":32}
            data=out/"dataset"
            build_dataset(config,data,demo=True)
            result=run_matrix(data,out,"dev",config)
            evaluate(out,data/"evaluation"); path=report(out)
            print(json.dumps({"planned":result["planned"],"completed":result["completed"],"failed":result["failed"],"report":str(path.resolve())},indent=2))
        elif args.command=="run":
            cfg=load_config(args.config) if args.config else None
            model=None
            if args.provider=="live" and not args.resume:
                model=dict((cfg or {}).get("model",{}),base_url=os.getenv("TRACEPATCH_BASE_URL",""),model=os.getenv("TRACEPATCH_MODEL",""))
            result=run_matrix(args.data,args.out,args.split,cfg,args.protocol,args.provider,args.allow_network,args.resume,args.replay_from,model)
            print(json.dumps({k:result[k] for k in ("planned","completed","failed","not_run","wall_seconds_this_invocation")},indent=2))
            if result["failed"]: return sys.exit(1)
        elif args.command=="freeze-protocol": freeze_protocol(args.run,args.out); print(args.out)
        elif args.command=="evaluate": evaluate(args.run,args.gold); print("Evaluation written to",args.run)
        elif args.command=="report": print(report(args.run).resolve())
    except (ValueError,FileNotFoundError) as exc:
        parser.exit(2,"TracePatch: "+str(exc)+"\n")
