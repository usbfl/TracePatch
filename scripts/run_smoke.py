"""Portable end-to-end smoke runner; refuses to overwrite an existing run."""
import argparse
import subprocess
import sys
from pathlib import Path


def main():
    p=argparse.ArgumentParser(); p.add_argument("--out",default="runs/smoke_local"); a=p.parse_args()
    root=Path(__file__).resolve().parents[1]; out=Path(a.out)
    if not out.is_absolute(): out=root/out
    if out.exists(): p.error("Output exists. Choose a new --out directory.")
    data=out/"dataset"; dev=out/"dev"; test=out/"test"; lock=out/"protocol.lock.json"
    commands=[['data','build','--config',str(root/'configs/smoke.yaml'),'--out',str(data)],['run','--config',str(root/'configs/smoke.yaml'),'--data',str(data),'--split','dev','--out',str(dev),'--provider','offline'],['freeze-protocol','--run',str(dev),'--out',str(lock)],['run','--protocol',str(lock),'--data',str(data),'--split','test','--out',str(test),'--provider','offline'],['evaluate','--run',str(test),'--gold',str(data/'evaluation')],['report','--run',str(test)]]
    for command in commands:
        print('> python -m tracepatch '+' '.join(command),flush=True)
        subprocess.run([sys.executable,'-m','tracepatch',*command],cwd=root,check=True)


if __name__=='__main__': main()
