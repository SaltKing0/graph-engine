from pathlib import Path
import gzip,json
ROOT=Path('/Users/niklas/Documents/ChatGPT/graph-engine/decision-solo')
OUT=Path('/tmp/issue91-y1-refresh/final-checks')
old=json.loads(gzip.decompress((ROOT/'docs/decision-evaluation-results/false-alert-development-v1/reviewed-v1/reviewed-report.json.gz').read_bytes()))
new=json.loads((OUT/'reviewed/report.json').read_bytes())
assert old['status']==new['status']=='complete' and len(old['results'])==len(new['results'])==13
assert old['source_manifest']==new['source_manifest']
assert old['review_sha256']==new['review_sha256'] and old['transcriptions_sha256']==new['transcriptions_sha256']
rows=[]
for a,b in zip(old['results'],new['results']):
 assert a['case_id']==b['case_id']
 assert a['source_input_sha256']==b['source_input_sha256']
 counts={}
 for mode in ('curated','proposed'):
  norm=lambda p:[{k:v for k,v in alert.items() if k!='candidate_id'} for alert in p['alerts']]
  assert norm(a['profiles'][mode])==norm(b['profiles'][mode])
  assert b['profiles'][mode]['error'] is None
  counts[mode]=len(b['profiles'][mode]['alerts'])
 rows.append(dict(case_id=b['case_id'],alerts=counts))
previous=json.loads(gzip.decompress((ROOT/'docs/decision-evaluation-results/false-alert-development-v1/reviewed-v1/production-controls.json.gz').read_bytes()))
current=json.loads((OUT/'production-controls.json').read_bytes())
for key in ['scores','gate_assessments','release_readiness']:
 assert previous[key]==current[key],key
assert not current['gate_assessments']['curated']['passed']
assert current['scores']['curated']['false_alert_rate']==dict(value=5/95,numerator=5,denominator=95)
assert current['scores']['proposed']['miss_rate']['numerator']==3
result=dict(status='pass',compared_to='30908637cf94bacd75d69e783fef222ea38944db',
 development_cases=rows,original_scores_and_gates_unchanged=True,independent_acceptance=False)
(OUT/'replay-comparison.json').write_text(json.dumps(result,indent=2)+'\n')
print('13 known development inputs/normalized alert outputs preserved; original scores, gates and thresholds identical.')
