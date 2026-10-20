import json,subprocess,time
from pathlib import Path
OUT=Path('/tmp/issue91-withdrawal-final');ROOT=Path('/tmp/issue91-withdrawal-history-3090863');P='/Users/niklas/Documents/ChatGPT/graph-engine/decision-solo/.venv/bin/python'
files=['false-alert-development-v1/verify_evidence.py','false-alert-development-v1/structured-v1/verify_evidence.py','false-alert-development-v1/reviewed-v1/verify_evidence.py','pr-review-v1/verify_review.py','solo-development-v1/verify_artifacts.py'];records=[]
for i,name in enumerate(files):
 cmd=[P,'docs/decision-evaluation-results/'+name];start=time.perf_counter();log=f'historical-{i}.log'
 with (OUT/log).open('x') as out:r=subprocess.run(cmd,cwd=ROOT,stdout=out,stderr=subprocess.STDOUT)
 row=dict(name='historical-'+str(i),argv=cmd,cwd=str(ROOT),source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),exit_code=r.returncode,elapsed_seconds=time.perf_counter()-start,log=log)
 records.append(row);print(json.dumps(row),flush=True)
(OUT/'historical-commands.json').write_text(json.dumps(records,indent=2)+'\n');raise SystemExit(any(r['exit_code'] for r in records))
