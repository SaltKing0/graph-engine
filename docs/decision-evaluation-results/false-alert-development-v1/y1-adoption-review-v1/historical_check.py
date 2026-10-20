from pathlib import Path
import subprocess,sys
root=Path.cwd();target=Path('/tmp/issue91-y1-adoption-review/history-a02')
subprocess.run(['git','clone','--shared','--no-checkout',str(root),str(target)],check=True)
subprocess.run(['git','-C',str(target),'checkout','--detach','a02f6eb9fdc8704e38d47f97c4f32b7e1dc2a7ca'],check=True)
subprocess.run([sys.executable,str(target/'docs/decision-evaluation-results/false-alert-development-v1/y1-adoption-plan-v1/verify.py')],cwd=target,check=True)
