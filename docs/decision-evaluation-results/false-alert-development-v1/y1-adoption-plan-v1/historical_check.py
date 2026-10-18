from pathlib import Path
import subprocess,sys
root=Path.cwd();target=Path('/tmp/issue91-y1-adoption/history-bf27')
subprocess.run(['git','clone','--shared','--no-checkout',str(root),str(target)],check=True)
subprocess.run(['git','-C',str(target),'checkout','--detach','bf27c81d7c03c6483359c979603dd56c9bd2de06'],check=True)
subprocess.run([sys.executable,str(target/'docs/decision-evaluation-results/false-alert-development-v1/y1-candidate-review-v1/verify.py')],cwd=target,check=True)
