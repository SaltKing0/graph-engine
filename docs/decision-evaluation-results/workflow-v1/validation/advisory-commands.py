from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess

root = Path('/private/tmp/issue81-advisories')
root.mkdir(exist_ok=True)
def run(profile):
    version = '3.14' if profile == 'core-3.14' else '3.12'
    target = '/private/tmp/issue57-' + version + '/bin/python'
    report = root / (profile + '.pip.json')
    args = ['-r', 'requirements.txt'] if profile == 'legacy' else ['.' if profile.startswith('core') else f'.[{profile}]']
    with (root / (profile + '.log')).open('w') as log:
        result = subprocess.run([target, '-m', 'pip', 'install', '--dry-run', '--ignore-installed', '--report', str(report), *args], stdout=log, stderr=log)
        if result.returncode == 0:
            result = subprocess.run(['/private/tmp/graph-engine-issue-57-tools/bin/python', '-m', 'tools.dependency_audit', str(report), '--pip-report', '--output', str(root / (profile + '.json'))], stdout=log, stderr=log)
    print(profile, result.returncode, (root / (profile + '.log')).read_text().splitlines()[-3:], flush=True)
with ThreadPoolExecutor(max_workers=3) as pool:
    list(pool.map(run, ['core', 'dev', 'mcp', 'pdf', 'core-3.14', 'st', 'legacy']))
