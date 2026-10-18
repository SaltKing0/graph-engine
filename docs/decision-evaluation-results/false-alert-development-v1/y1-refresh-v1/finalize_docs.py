from pathlib import Path
import hashlib,json,shutil,subprocess,time
ROOT=Path('/Users/niklas/Documents/ChatGPT/graph-engine/decision-solo');OUT=Path('/tmp/issue91-y1-refresh/final-checks');HERE=ROOT/'docs/decision-evaluation-results/false-alert-development-v1/y1-refresh-v1';P=str(ROOT/'.venv/bin/python')
commands=json.loads((OUT/'commands.json').read_bytes())
assert len(commands)==10 and all(c['exit_code']==0 for c in commands)
for name in ['commands.json','full.log','full-command.json']:shutil.copyfile(OUT/name,HERE/name)
for p in OUT.glob('*-command.json'):shutil.copyfile(p,HERE/p.name)
shutil.copyfile(Path('/tmp/issue91-y1-refresh/finalize_docs.py'),HERE/'finalize_docs.py')
checks=[]

def check(name,args):
 start=time.perf_counter()
 with (OUT/(name+'.log')).open('w') as stream:
  result=subprocess.run(args,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
 row=dict(name=name,argv=args,cwd=str(ROOT),exit_code=result.returncode,elapsed_seconds=time.perf_counter()-start,log=name+'.log')
 checks.append(row);print(json.dumps(row),flush=True)
 if result.returncode:raise SystemExit(result.returncode)
 shutil.copyfile(OUT/(name+'.log'),HERE/(name+'.log'))

check('references',[P,str(HERE/'check_references.py')])
check('replay-comparison',[P,str(HERE/'compare_replays.py')])
check('diff-check',['git','diff','--check'])
(HERE/'documentation-checks.json').write_text(json.dumps(checks,indent=2)+'\n')

def manifest():
 files={str(p.relative_to(HERE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.rglob('*')) if p.is_file() and p.name!='manifest.json' and '__pycache__' not in p.parts}
 (HERE/'manifest.json').write_text(json.dumps(dict(schema='dm.y1-refresh-evidence/1',files=files),indent=2)+'\n')
manifest()
check('verification',[P,str(HERE/'verify.py')])
(HERE/'documentation-checks.json').write_text(json.dumps(checks,indent=2)+'\n')
manifest()
with (OUT/'verification-final.log').open('w') as stream:
 result=subprocess.run([P,str(HERE/'verify.py')],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
print('Final artifact/restore verification exit:',result.returncode,flush=True)
raise SystemExit(result.returncode)
