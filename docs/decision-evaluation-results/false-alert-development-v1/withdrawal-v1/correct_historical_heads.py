import json,subprocess,time
from pathlib import Path
OUT=Path('/tmp/issue91-withdrawal-final');ROOT=Path('/tmp/issue91-historical-evidence-fb2fff2');P='/Users/niklas/Documents/ChatGPT/graph-engine/decision-solo/.venv/bin/python'
initial=json.loads((OUT/'historical-commands.json').read_bytes())
(OUT/'historical-initial-commands.json').write_text(json.dumps(initial,indent=2)+'\n')
rows=[]
for i,row in enumerate(initial):
 if row['exit_code']==0: rows.append(row);continue
 cmd=row['argv'];log=f'historical-{i}-correct-head.log';start=time.perf_counter()
 with (OUT/log).open('x') as stream:r=subprocess.run(cmd,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
 updated=dict(row,cwd=str(ROOT),source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),exit_code=r.returncode,elapsed_seconds=time.perf_counter()-start,log=log)
 rows.append(updated);print(json.dumps(updated),flush=True)
(OUT/'historical-commands-final.json').write_text(json.dumps(rows,indent=2)+'\n');raise SystemExit(any(r['exit_code'] for r in rows))
