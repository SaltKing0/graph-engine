import concurrent.futures,json,os,subprocess,sys,time,platform
from pathlib import Path
ROOT=Path('/Users/niklas/Documents/ChatGPT/graph-engine/decision-solo')
OUT=Path('/tmp/issue91-y1-refresh/final-checks')
ENV={**os.environ,'GRAPH_ENGINE_TEST_D3':'/tmp/decision-solo-d3.v7.min.js','PLAYWRIGHT_BROWSERS_PATH':'/tmp/decision-solo-playwright'}
P=str(ROOT/'.venv/bin/python')
checks={
 'full':[P,'-m','pytest','tests/','-q','-rs'],
 'focused':[P,'-m','pytest','tests/test_decision_refresh_basis.py','tests/test_decision_support_paths.py','tests/test_decision_review.py','tests/test_decision_impact.py','tests/test_decision_reviewed_observations.py','tests/test_decision_observations.py','tests/test_decision_source_updates.py','tests/test_decision_workflow.py','tests/test_decision_solo.py','-q'],
 'refresh':[P,'docs/decision-evaluation-results/false-alert-development-v1/y1-refresh-v1/refresh.py','--output',str(OUT/'refresh')],
 'reviewed-development':[P,'-m','tools.decision_benchmark.reviewed_development','--output',str(OUT/'reviewed')],
 'memory-smoke':[P,'-m','tools.memory_benchmark','--smoke','--check','--output',str(OUT/'memory-smoke.json')],
 'decision-controls':[P,'-m','tools.decision_benchmark','--split','all','--check','--output',str(OUT/'decision-controls.json')],
 'workflow':[P,'-m','examples.decision_workflow','--output',str(OUT/'workflow.json')],
 'production-controls':[P,'-m','tools.decision_benchmark.production','--split','all','--output',str(OUT/'production-controls.json')],
 'integrity':[P,'-m','tools.decision_integrity','--output',str(OUT/'integrity')],
 'pip-check':[P,'-m','pip','check'],
}
(OUT/'environment.json').write_text(json.dumps(dict(python=sys.version,platform=platform.platform(),executable=sys.executable,environment={k:ENV[k] for k in ['GRAPH_ENGINE_TEST_D3','PLAYWRIGHT_BROWSERS_PATH']},source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()),indent=2)+'\n')
def check(name):
 start=time.perf_counter()
 with (OUT/(name+'.log')).open('x') as out:
  result=subprocess.run(checks[name],cwd=ROOT,env=ENV,stdout=out,stderr=subprocess.STDOUT)
 record=dict(name=name,argv=checks[name],cwd=str(ROOT),environment={k:ENV[k] for k in ['GRAPH_ENGINE_TEST_D3','PLAYWRIGHT_BROWSERS_PATH']},exit_code=result.returncode,elapsed_seconds=time.perf_counter()-start,log=name+'.log')
 (OUT/(name+'-command.json')).write_text(json.dumps(record,indent=2)+'\n')
 print(json.dumps(record),flush=True)
 return record
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 records=list(pool.map(check,sys.argv[1:] or checks))
(OUT/'commands.json').write_text(json.dumps(records,indent=2)+'\n')
raise SystemExit(any(r['exit_code'] for r in records))
