import json,os,subprocess,sys,time,platform
from pathlib import Path
ROOT=Path('/Users/niklas/Documents/ChatGPT/graph-engine/decision-solo')
OUT=Path('/tmp/issue91-structured-final')
ENV={**os.environ,'GRAPH_ENGINE_TEST_D3':'/tmp/decision-solo-d3.v7.min.js','PLAYWRIGHT_BROWSERS_PATH':'/tmp/decision-solo-playwright'}
P=str(ROOT/'.venv/bin/python')
checks={
 'full':[P,'-m','pytest','tests/','-q','-rs'],
 'focused':[P,'-m','pytest','tests/test_decision_observations.py','tests/test_decision_source_updates.py','tests/test_decision_workflow.py','tests/test_decision_solo.py','-q'],
 'capture':[P,'-m','tools.decision_benchmark.structured_development','--capture','--output',str(OUT/'capture')],
 'memory-smoke':[P,'-m','tools.memory_benchmark','--smoke','--check','--output',str(OUT/'memory-smoke.json')],
 'decision-controls':[P,'-m','tools.decision_benchmark','--split','all','--check','--output',str(OUT/'decision-controls.json')],
 'workflow':[P,'-m','examples.decision_workflow','--output',str(OUT/'workflow.json')],
 'production-controls':[P,'-m','tools.decision_benchmark.production','--split','all','--output',str(OUT/'production-controls.json')],
 'integrity':[P,'-m','tools.decision_integrity','--output',str(OUT/'integrity')],
 'pip-check':[P,'-m','pip','check'],
 'old-noop-evidence':[P,'docs/decision-evaluation-results/false-alert-development-v1/verify_evidence.py'],
 'old-review-evidence':[P,'docs/decision-evaluation-results/pr-review-v1/verify_review.py'],
 'old-solo-evidence':[P,'docs/decision-evaluation-results/solo-development-v1/verify_artifacts.py'],
}
for name in sys.argv[1:]:
 start=time.perf_counter()
 with (OUT/(name+'.log')).open('x') as out:
  result=subprocess.run(checks[name],cwd=ROOT,env=ENV,stdout=out,stderr=subprocess.STDOUT)
 record=dict(name=name,argv=checks[name],cwd=str(ROOT),exit_code=result.returncode,elapsed_seconds=time.perf_counter()-start,log=name+'.log')
 (OUT/(name+'-command.json')).write_text(json.dumps(record,indent=2)+'\n')
 print(json.dumps(record),flush=True)
