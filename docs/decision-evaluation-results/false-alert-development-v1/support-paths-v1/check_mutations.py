"""Reject overclaimed acceptance and damaged captured evidence; no new cases."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
from verify import validate_report

HERE = Path(__file__).resolve().parent
report = json.loads(gzip.decompress((HERE / 'support-paths-report.json.gz').read_bytes()))
validate_report(report)
mutations = ['human', 'independent', 'coverage', 'benefit', 'old-review', 'old-content',
             'remaining-X1', 'missing-withdrawal', 'auto-adopt', 'resolve-finding', 'inherit-review',
             'false-unit', 'uncertain-new-basis']
for name in mutations:
    p = deepcopy(report)
    r = p['result']
    if name == 'human': p['author']['human'] = True
    if name == 'independent': p['independent_acceptance'] = True
    if name == 'coverage': p['independent_final_coverage']['positive'] = 1
    if name == 'benefit': p['product_benefit'] = {'improvement': 1}
    if name == 'old-review': r['final']['old_claim']['events'] = []
    if name == 'old-content': r['final']['historical_claim']['record']['payload']['text'] = 'overwritten'
    if name == 'remaining-X1': r['comparison']['candidates'][0]['support']['remaining'][0]['evidence'] = r['references']['evidence']['X1']
    if name == 'missing-withdrawal': r['comparison']['candidates'][0]['support']['removed'] = []
    if name == 'auto-adopt': r['final']['decision']['state']['decision'] = 'current'
    if name == 'resolve-finding': r['final']['finding']['state']['finding_workflow'] = 'resolved'
    if name == 'inherit-review': r['proposal']['claim']['events'] = r['initial']['claim']['events']
    if name == 'false-unit': r['assessment']['declared_unit'] = 'percent'
    if name == 'uncertain-new-basis': r['final']['claim']['basis_changed'] = True
    try:
        validate_report(p)
    except (AssertionError, ValueError):
        print(name + ': rejected')
    else:
        raise AssertionError('Invalid captured evidence accepted: ' + name)
print('13 artifact mutations rejected; no new independent cases or judgments.')
