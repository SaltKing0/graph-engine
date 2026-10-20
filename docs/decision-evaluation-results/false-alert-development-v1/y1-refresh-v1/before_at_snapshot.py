import json,os,shutil,subprocess,time
from pathlib import Path
ROOT=Path('/Users/niklas/Documents/ChatGPT/graph-engine/decision-solo');OUT=Path('/tmp/issue91-y1-refresh');clone=OUT/'history-22'
subprocess.run(['git','clone','--shared','--no-checkout',str(ROOT),str(clone)],check=True,capture_output=True)
subprocess.run(['git','-C',str(clone),'checkout','--detach','22e398a572397ca378a25ac93dc4a3b71666dd98'],check=True,capture_output=True)
shutil.copyfile(ROOT/'tests/test_decision_refresh_basis.py',clone/'tests/test_decision_refresh_basis.py')
args=[str(ROOT/'.venv/bin/python'),'-m','pytest','tests/test_decision_refresh_basis.py','-q']
start=time.perf_counter()
with (OUT/'before-fix-snapshot.log').open('w') as f:
 result=subprocess.run(args,cwd=clone,env={**os.environ,'PYTHONPATH':str(clone)},stdout=f,stderr=subprocess.STDOUT)
meta=dict(argv=args,cwd=str(clone),source_commit='22e398a572397ca378a25ac93dc4a3b71666dd98',environment=dict(PYTHONPATH=str(clone)),exit_code=result.returncode,elapsed_seconds=time.perf_counter()-start,expected_failure=True)
(OUT/'before-fix-snapshot-command.json').write_text(json.dumps(meta,indent=2)+'\n')
print(json.dumps(meta),flush=True)
assert result.returncode==1 and '4 failed' in (OUT/'before-fix-snapshot.log').read_text()
