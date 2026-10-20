from pathlib import Path
import subprocess,sys
root=Path.cwd();target=Path('/tmp/issue91-y1-candidates/history-08')
subprocess.run(['git','clone','--shared','--no-checkout',str(root),str(target)],check=True)
subprocess.run(['git','-C',str(target),'checkout','--detach','08f55ea4120336db83ada29ea2c305f777186fab'],check=True)
subprocess.run([sys.executable,str(target/'docs/decision-evaluation-results/false-alert-development-v1/y1-refresh-v1/verify.py')],cwd=target,check=True)
