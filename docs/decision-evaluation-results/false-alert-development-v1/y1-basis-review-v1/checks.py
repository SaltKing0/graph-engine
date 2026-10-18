from pathlib import Path
import hashlib,json,shutil,subprocess,time
ROOT=Path('/Users/niklas/Documents/ChatGPT/graph-engine/decision-solo')
OUT=Path('/tmp/issue91-y1-review')
HERE=ROOT/'docs/decision-evaluation-results/false-alert-development-v1/y1-basis-review-v1'
P=str(ROOT/'.venv/bin/python')
records=[dict(name='prior-evidence',argv=[P,'docs/decision-evaluation-results/false-alert-development-v1/support-paths-v1/verify.py'],cwd=str(ROOT),exit_code=0,elapsed_seconds=None,log='prior-evidence.log',note='Executed before adding the new sibling audit, on snapshot 75b3194; elapsed time not instrumented.'),dict(name='focused',argv=[P,'-m','pytest','tests/test_decision_support_paths.py','tests/test_decision_reviewed_observations.py','tests/test_decision_observations.py','tests/test_decision_source_updates.py','tests/test_decision_workflow.py','tests/test_decision_solo.py','-q'],cwd=str(ROOT),exit_code=0,elapsed_seconds=None,pytest_reported_seconds=66.21,log='focused.log'),dict(name='capture',argv=[P,'docs/decision-evaluation-results/false-alert-development-v1/y1-basis-review-v1/review.py','--capture','docs/decision-evaluation-results/false-alert-development-v1/y1-basis-review-v1/review.json'],cwd=str(ROOT),exit_code=0,elapsed_seconds=None,log='capture.log')]
assert '117 passed in 66.21s' in (OUT/'focused.log').read_text()
assert 'Complete artifact inventory' in (OUT/'prior-evidence.log').read_text()
for name in ['prior-evidence','focused','capture']:shutil.copyfile(OUT/(name+'.log'),HERE/(name+'.log'))
shutil.copyfile(OUT/'checks.py',HERE/'checks.py')

def check(name,args):
 start=time.perf_counter()
 with (OUT/(name+'.log')).open('w') as f:
  result=subprocess.run(args,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
 row=dict(name=name,argv=args,cwd=str(ROOT),exit_code=result.returncode,elapsed_seconds=time.perf_counter()-start,log=name+'.log')
 records.append(row);print(json.dumps(row),flush=True)
 if result.returncode:raise SystemExit(result.returncode)
 shutil.copyfile(OUT/(name+'.log'),HERE/(name+'.log'))

(HERE/'commands.json').write_text(json.dumps(records,indent=2)+'\n')
check('references',[P,str(HERE/'check_references.py')])
check('diff-check',['git','diff','--check'])
(HERE/'commands.json').write_text(json.dumps(records,indent=2)+'\n')

def manifest():
 files={str(p.relative_to(HERE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.rglob('*')) if p.is_file() and p.name!='manifest.json' and '__pycache__' not in p.parts}
 (HERE/'manifest.json').write_text(json.dumps(dict(schema='dm.y1-source-review-manifest/1',files=files),indent=2)+'\n')
manifest()
check('verification',[P,str(HERE/'review.py')])
(HERE/'commands.json').write_text(json.dumps(records,indent=2)+'\n')
manifest()
with (OUT/'verification-final.log').open('w') as f:
 result=subprocess.run([P,str(HERE/'review.py')],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
print('Final inventory verification exit:',result.returncode,flush=True)
raise SystemExit(result.returncode)
