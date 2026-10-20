import concurrent.futures,json,os,subprocess,time
from pathlib import Path
ROOT=Path('/Users/niklas/Documents/ChatGPT/graph-engine/decision-solo');OUT=Path('/tmp/issue91-withdrawal-final');P=str(ROOT/'.venv/bin/python')
BASE='docs/decision-evaluation-results/false-alert-development-v1/withdrawal-v1/'
checks={
 'source-audit':[P,BASE+'check_audit.py'],
 'replay':[P,BASE+'verify.py','--replay',str(OUT/'replay')],
 'focused':[P,'-m','pytest','tests/test_decision_reviewed_observations.py','tests/test_decision_observations.py','tests/test_decision_source_updates.py','tests/test_decision_workflow.py','tests/test_decision_solo.py','-q'],
}
def run(name):
 start=time.perf_counter()
 with (OUT/(name+'.log')).open('x') as stream:
  result=subprocess.run(checks[name],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
 row=dict(name=name,argv=checks[name],cwd=str(ROOT),exit_code=result.returncode,elapsed_seconds=time.perf_counter()-start,log=name+'.log')
 (OUT/(name+'-command.json')).write_text(json.dumps(row,indent=2)+'\n');print(json.dumps(row),flush=True);return row
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor: rows=list(executor.map(run,checks))
(OUT/'commands.json').write_text(json.dumps(rows,indent=2)+'\n')
raise SystemExit(any(r['exit_code'] for r in rows))
