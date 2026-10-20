import concurrent.futures,json,subprocess,time
from pathlib import Path
ROOT=Path('/Users/niklas/Documents/ChatGPT/graph-engine/decision-solo');OUT=Path('/tmp/issue91-y1-refresh/final-checks');P=str(ROOT/'.venv/bin/python')
old=json.loads((ROOT/'docs/decision-evaluation-results/false-alert-development-v1/withdrawal-v1/historical-commands-final.json').read_bytes())
rows=[dict(name=r['name'],argv=r['argv'],cwd=r['cwd'],source_commit=r['source_commit']) for r in old]
rows.append(dict(name='historical-5',argv=[P,'docs/decision-evaluation-results/false-alert-development-v1/withdrawal-v1/verify.py'],cwd='/tmp/issue91-support-paths-history-ad757775',source_commit='ad757775ff6a03af46dcf6ac6872fc81b4f8ae08'))
clone=Path('/tmp/issue91-y1-refresh/history-75')
subprocess.run(['git','clone','--shared','--no-checkout',str(ROOT),str(clone)],check=True,capture_output=True)
subprocess.run(['git','-C',str(clone),'checkout','--detach','75b319445d8976ce3f74c7875f686e12cb8eba85'],check=True,capture_output=True)
rows.append(dict(name='historical-6',argv=[P,'docs/decision-evaluation-results/false-alert-development-v1/support-paths-v1/verify.py'],cwd=str(clone),source_commit='75b319445d8976ce3f74c7875f686e12cb8eba85'))
rows.append(dict(name='historical-7',argv=[P,'docs/decision-evaluation-results/false-alert-development-v1/y1-basis-review-v1/review.py'],cwd='/tmp/issue91-y1-refresh/history-22',source_commit='22e398a572397ca378a25ac93dc4a3b71666dd98'))
def check(row):
 start=time.perf_counter();log=row['name']+'.log'
 with (OUT/log).open('w') as stream:
  result=subprocess.run(row['argv'],cwd=row['cwd'],stdout=stream,stderr=subprocess.STDOUT)
 row.update(exit_code=result.returncode,elapsed_seconds=time.perf_counter()-start,log=log)
 print(json.dumps(row),flush=True);return row
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(check,rows))
(OUT/'historical-commands.json').write_text(json.dumps(results,indent=2)+'\n')
raise SystemExit(any(r['exit_code'] for r in results))
