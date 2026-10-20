import json,subprocess,time
from pathlib import Path
ROOT=Path('/tmp/issue91-historical-evidence-fb2fff2')
OUT=Path('/tmp/issue91-reviewed-final-v2')
P='/Users/niklas/Documents/ChatGPT/graph-engine/decision-solo/.venv/bin/python'
files=['docs/decision-evaluation-results/false-alert-development-v1/verify_evidence.py','docs/decision-evaluation-results/false-alert-development-v1/structured-v1/verify_evidence.py','docs/decision-evaluation-results/pr-review-v1/verify_review.py','docs/decision-evaluation-results/solo-development-v1/verify_artifacts.py']
records=[]
for i,path in enumerate(files):
 start=time.perf_counter(); log=f'historical-{i}.log'
 with (OUT/log).open('x') as stream:
  result=subprocess.run([P,path],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
 record=dict(name=f'historical-{i}',argv=[P,path],cwd=str(ROOT),source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),exit_code=result.returncode,elapsed_seconds=time.perf_counter()-start,log=log)
 records.append(record);print(json.dumps(record),flush=True)
(OUT/'historical-commands.json').write_text(json.dumps(records,indent=2)+'\n')
raise SystemExit(any(r['exit_code'] for r in records))
