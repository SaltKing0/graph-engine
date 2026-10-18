import concurrent.futures,json,subprocess,time
from pathlib import Path
ROOT=Path('/Users/niklas/Documents/ChatGPT/graph-engine/decision-solo')
OUT=Path('/tmp/issue91-support-paths-final')
P=str(ROOT/'.venv/bin/python')
rows=json.loads((ROOT/'docs/decision-evaluation-results/false-alert-development-v1/withdrawal-v1/historical-commands-final.json').read_bytes())
clone=Path('/tmp/issue91-support-paths-history-ad757775')
subprocess.run(['git','clone','--shared','--no-checkout',str(ROOT),str(clone)],check=True,capture_output=True)
subprocess.run(['git','-C',str(clone),'checkout','--detach','ad757775ff6a03af46dcf6ac6872fc81b4f8ae08'],check=True,capture_output=True)
rows.append(dict(name='historical-5',argv=[P,'docs/decision-evaluation-results/false-alert-development-v1/withdrawal-v1/verify.py'],cwd=str(clone),source_commit='ad757775ff6a03af46dcf6ac6872fc81b4f8ae08'))
def check(row):
 start=time.perf_counter(); log=row['name']+'.log'
 with (OUT/log).open('x') as f:
  rc=subprocess.run(row['argv'],cwd=row['cwd'],stdout=f,stderr=subprocess.STDOUT).returncode
 result={**row,'exit_code':rc,'elapsed_seconds':time.perf_counter()-start,'log':log}
 print(json.dumps(result),flush=True)
 return result
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
 results=list(pool.map(check,rows))
(OUT/'historical-commands.json').write_text(json.dumps(results,indent=2)+'\n')
raise SystemExit(any(r['exit_code'] for r in results))
