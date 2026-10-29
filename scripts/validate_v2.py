"""Validate frozen files, report data and all persisted SQLite budgets."""
import argparse
import base64
import csv
import json
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracepatch.common import read_json, source_hash, file_hash, digest
from tracepatch.experiment import unseal, verify_frozen
from tracepatch.workflow.evaluate import verify_bundle


def check(run):
    run=Path(run); frozen, protocol=verify_bundle(run)
    assert protocol['source_hash']==source_hash()
    ev=read_json(run/'evaluation.json')
    assert ev['frozen_hash']==read_json(run/'frozen.json')['hash']
    for name,h in ev['csv_hashes'].items(): assert file_hash(run/name)==h
    with (run/'metrics.csv').open(encoding='utf-8-sig') as f: rows=list(csv.DictReader(f))
    assert len(rows)==len(ev['metrics'])
    for row,metric in zip(rows,ev['metrics']):
        for key in ('task_accuracy','final_task_accuracy','recontamination_rate','spent_units'):
            assert (row[key]=='' if metric[key] is None else abs(float(row[key])-metric[key])<1e-12)
    calls=0; databases=0
    for r in frozen['runs']:
        s=unseal(read_json(run/r['state_path']))
        assert s['status']=='completed'
        ledger=s['repair']['ledger']
        assert ledger['spent_units']<=r['budget'] and ledger['reserved_units']==0
        calls+=s['model_requests']+ledger['model_requests']
        for name in ('repair','workflow'):
            dbfile=run/'db'/r['run_id']/(name+'.sqlite')
            checkpoint=read_json(sorted(dbfile.with_suffix('.checkpoints').glob('*.json'))[-1])
            assert digest(checkpoint['database'])==checkpoint['hash']
            assert base64.b64decode(checkpoint['database'],validate=True)==dbfile.read_bytes()
            with sqlite3.connect(':memory:') as db:
                db.deserialize(dbfile.read_bytes())
                assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                spent,reserved=db.execute('SELECT spent,reserved FROM run').fetchone()
                assert reserved==0
                assert spent==(ledger['spent_units'] if name=='repair' else 0)
            db.close()
            databases+=1
    assert calls==0
    return {'run':str(run),'planned':len(frozen['runs']),'completed':ev['completed'],'failed':ev['failed'],
            'sqlite_databases_checked':databases,'source_hash_matches':True,'csv_matches_json':True,'model_requests':calls}


def main():
    p=argparse.ArgumentParser(); p.add_argument('runs',nargs='+'); p.add_argument('--out',default='validation/v2_artifact_checks.json'); args=p.parse_args()
    results=[check(run) for run in args.runs]
    path=Path(args.out); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2))

if __name__=='__main__': main()
