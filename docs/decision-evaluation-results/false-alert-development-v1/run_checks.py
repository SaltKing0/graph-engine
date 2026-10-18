import json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path('/Users/niklas/Documents/ChatGPT/graph-engine/decision-solo')
OUT=Path('/tmp/issue91-validation')
ENV={**os.environ,'GRAPH_ENGINE_TEST_D3':'/tmp/decision-solo-d3.v7.min.js','PLAYWRIGHT_BROWSERS_PATH':'/tmp/decision-solo-playwright'}
PYTHON=str(ROOT/'.venv/bin/python')
checks={
 'full-final': [PYTHON,'-m','pytest','tests/','-q','-rs'],
 'focused-final': [PYTHON,'-m','pytest','tests/test_decision_source_updates.py','tests/test_decision_workflow.py','tests/test_decision_solo.py','-q'],
 'pip-check': [PYTHON,'-m','pip','check'],
 'memory-smoke': [PYTHON,'-m','tools.memory_benchmark','--smoke','--check','--output',str(OUT/'memory-smoke.json')],
 'decision-controls': [PYTHON,'-m','tools.decision_benchmark','--split','all','--check','--output',str(OUT/'decision-controls.json')],
 'workflow': [PYTHON,'-m','examples.decision_workflow','--output',str(OUT/'workflow.json')],
 'production-controls': [PYTHON,'-m','tools.decision_benchmark.production','--split','all','--output',str(OUT/'production-controls.json')],
 'solo-development': [PYTHON,'-m','tools.decision_benchmark.solo','--output',str(OUT/'solo-development.json')],
 'integrity-final': [PYTHON,'-m','tools.decision_integrity','--output',str(OUT/'integrity-final')],
 'old-review-verifier': [PYTHON,'docs/decision-evaluation-results/pr-review-v1/verify_review.py'],
 'old-solo-verifier': [PYTHON,'docs/decision-evaluation-results/solo-development-v1/verify_artifacts.py'],
 'diff-check': ['git','diff','--check'],
}
for name in sys.argv[1:]:
 start=time.perf_counter()
 with (OUT/(name+'.log')).open('x') as out:
  result=subprocess.run(checks[name],cwd=ROOT,env=ENV,stdout=out,stderr=subprocess.STDOUT)
 record=dict(name=name,argv=checks[name],cwd=str(ROOT),exit_code=result.returncode,elapsed_seconds=time.perf_counter()-start,log=name+'.log')
 (OUT/(name+'-command.json')).write_text(json.dumps(record,indent=2)+'\n')
 print(json.dumps(record),flush=True)
