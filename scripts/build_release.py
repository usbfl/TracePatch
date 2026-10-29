"""Sequential release checks; use a fresh output tree for a new release."""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
(root/'validation').mkdir(exist_ok=True)
commands = [
 ('pytest', ['-m', 'pytest', '-q']),
 ('v2_demo', ['-m', 'tracepatch', 'v2-demo', '--out', 'runs/v2_demo']),
 ('v2_smoke', ['-m', 'tracepatch', 'v2-smoke', '--out', 'runs/v2_smoke']),
 ('legacy_smoke', ['scripts/run_smoke.py', '--out', 'runs/legacy_regression']),
 ('v2_artifact_checks', ['scripts/validate_v2.py', 'runs/v2_demo/dev', 'runs/v2_smoke/dev', 'runs/v2_smoke/test'])
]
for name, command in commands:
    print('Running '+name, flush=True)
    with (root/'validation'/(name+'.txt')).open('w',encoding='utf-8') as f:
        result=subprocess.run([sys.executable,*command],cwd=root,stdout=f,stderr=subprocess.STDOUT)
    print(name+': exit '+str(result.returncode),flush=True)
    if result.returncode:
        print((root/'validation'/(name+'.txt')).read_text(encoding='utf-8'),flush=True)
        raise SystemExit(result.returncode)
