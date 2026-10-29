"""Cross-check immutable JSON/CSV/SQLite reports after generation."""
import csv
import json
import sqlite3
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from tracepatch.common import read_json, source_hash
from tracepatch.experiment import verify_frozen, unseal


class HTMLCheck(HTMLParser):
    def __init__(self):
        super().__init__(); self.tables=0; self.external=[]; self.scripts=0
    def handle_starttag(self,tag,attrs):
        if tag=='table': self.tables+=1
        if tag=='script': self.scripts+=1
        for key,value in attrs:
            if key in ('src','href') and value and value.startswith(('http:','https:','//')): self.external.append(value)


def main():
    root=Path(__file__).resolve().parents[1]; summary={}
    for name in ('demo','smoke/dev','smoke/test','diagnostic/results'):
        run=root/'runs'/name; frozen,session=verify_frozen(run)
        assert session['source_hash']==source_hash(),name
        details={}
        if (run/'evaluation.json').exists():
            ev=read_json(run/'evaluation.json')
            with (run/'metrics.csv').open(encoding='utf-8-sig') as f: rows=list(csv.DictReader(f))
            assert len(rows)==len(ev['metrics'])
            for row,m in zip(rows,ev['metrics']):
                for key in ('overall_accuracy','coverage','stale_error_reuse','benign_unavailability','spent_units'):
                    if m[key] is None: assert row[key]==''
                    else: assert abs(float(row[key])-m[key])<1e-12
            parser=HTMLCheck(); parser.feed((run/'report.html').read_text(encoding='utf-8'))
            assert parser.tables>0 and not parser.external and parser.scripts==0
            details.update(csv_matches_json=True,html_external_dependencies=[],html_structure_checked=True)
        calls=reserved=0
        for item in frozen['runs']:
            state=unseal(read_json(run/'states'/(item['run_id']+'.json')))
            assert state['status']!='failed',state.get('reason')
            calls+=state['ledger']['model_requests']; reserved+=state['ledger']['reserved_units']
            db=sqlite3.connect(run/'db'/(item['run_id']+'.sqlite'))
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok',item['run_id']
            assert db.execute('SELECT spent FROM run').fetchone()[0]==state['ledger']['spent_units']
            assert db.execute('SELECT count(*) FROM versions').fetchone()[0]==len(state['records'])
            db.close()
        assert calls==reserved==0
        summary[name]=dict(planned=frozen['planned'],completed=frozen['completed'],statuses=dict(Counter(x['status'] for x in frozen['runs'])),model_calls=calls,remaining_reservations=reserved,source_matches=True,sqlite_integrity='ok',wall_seconds=frozen['wall_seconds_this_invocation'],**details)
    (root/'validation'/'artifact_checks.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__=='__main__': main()
