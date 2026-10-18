from copy import deepcopy
import importlib.util,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
spec=importlib.util.spec_from_file_location('withdrawal_audit',HERE/'verify.py');audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
sources,case,_=audit.prepared();packet=json.loads((HERE/'source-audit.json').read_bytes())
result=audit.assessment(packet,sources,case)
assert result['supports_stated_rule_as_declared'] and result['threshold']=='0.7' and result['value']=='0.8'
assert result['independently_reviewed_measurement_independence'] is result['statistical_sufficiency'] is None
assert not result['accepted_runtime_sufficiency'] and not result['unchanged_old_basis_safe_to_retain']
mutations=['source-hash','missing-unit','wrong-numeric-value','threshold-from-measurement','value-from-X1',
           'missing-condition','swapped-condition','root-from-X1','wrong-subject','fabricated-human','fabricated-independence','gold-key','unit-role']
for name in mutations:
 p=deepcopy(packet)
 if name=='source-hash':p['sources'][p['rule']['source_id']]['text_sha256']='0'*64
 if name=='missing-unit':p['rule']['unit']=None
 if name=='wrong-numeric-value':p['remaining']['value']['value']='0.9'
 if name=='threshold-from-measurement':p['rule']['threshold']=p['remaining']['value']
 if name=='value-from-X1':
  from tools.decision_benchmark.observations import binding
  p['remaining']['value']=binding(sources[p['rule']['source_id']]['text'],'0.8',kind='decimal')
 if name=='missing-condition':p['remaining']['conditions']['environment']=None
 if name=='swapped-condition':p['remaining']['conditions']['environment']=p['remaining']['conditions']['workload']
 if name=='root-from-X1':p['remaining']['measurement_root']=p['withdrawn']['measurement_root']
 if name=='wrong-subject':p['update']['remaining_subject']=p['update']['withdrawn_subject']
 if name=='fabricated-human':p['author']['human']=True
 if name=='fabricated-independence':p['author']['independent']=True
 if name=='gold-key':p['expected_impact']=False
 if name=='unit-role':p['rule']['unit']=p['rule']['action']
 try:audit.assessment(p,sources,case)
 except ValueError: print(name+': rejected')
 else: raise AssertionError('Invalid interpretation accepted: '+name)
print('Declared-rule assessment passed; all 13 adversarial source/role/acceptance mutations rejected.')
