"""Implementing-agent transcription of already exposed development sources only.

This authoring layout has no expected impacts, labels, paths or reviewer votes.
The runtime validator subsequently binds every atom to the frozen source text.
"""
from pathlib import Path
import json,re
from tools.decision_benchmark.structured_development import development_inputs, TRANSCRIPTIONS
from tools.decision_benchmark.observations import AUTHOR,DIMENSIONS,binding,validate
from tools.decision_benchmark.corpus import digest
sources,cases=development_inputs()
rows={key:dict(source_id=key,text_sha256=digest(src['text'].encode()),facts=[]) for key,src in sources.items()}

def fact(key,fid,kind='measurement'):
 return dict(id=fid,kind=kind,subject=None,metric=None,conditions={k:None for k in DIMENSIONS},
             measurement_lineage=None,observed_at=None,availability=None,
             limitations=['Selected source transcription by implementing agent; semantic role and completeness need review.'])

def b(key,raw,**kw): return binding(sources[key]['text'],raw,**kw)

families=('comparable','changed-conditions','time-only','duplicate-citation','surviving-support')
for family in families:
 key=f'controls-v2/{family}-basis';f=fact(key,'observation-X1')
 f['subject']=b(key,'X1')
 f['metric']=dict(name=b(key,'recall'),value=b(key,'0.8',kind='decimal'),unit=b(key,'fraction'),sample_count=None)
 for name,raw in dict(workload='W',environment='E',code='C',corpus='H',protocol='P').items():
  phrase=sources[key]['text'].index(name+' '+raw)
  f['conditions'][name]=b(key,raw,start=phrase+len(name)+1)
 f['measurement_lineage']=b(key,'run-X1');rows[key]['facts'].append(f)
 if family=='surviving-support':
  f=fact(key,'observation-Y1');start=sources[key]['text'].index('Separate support Y1')
  f['subject']=b(key,'Y1',start=start)
  f['metric']=dict(name=b(key,'recall',start=start),value=b(key,'0.8',start=start,kind='decimal'),unit=None,sample_count=None)
  f['measurement_lineage']=b(key,'run-Y1');f['limitations'].append('Same-conditions prose was not expanded into inherited dimensions or independent support.')
  rows[key]['facts'].append(f)
for family in ('comparable','changed-conditions','time-only'):
 key=f'controls-v2/{family}-update';f=fact(key,'observation-X2');f['subject']=b(key,'X2')
 metric='0.8' if family=='time-only' else '0.2'
 f['metric']=dict(name=b(key,'recall'),value=b(key,metric,kind='decimal'),unit=b(key,'fraction'),sample_count=None)
 for name,raw in dict(workload='W2' if family=='changed-conditions' else 'W',environment='E',code='C',
                      corpus='H2' if family=='changed-conditions' else 'H',protocol='P').items():
  prefix='same protocol ' if family=='comparable' and name=='protocol' else name+' '
  phrase=sources[key]['text'].index(prefix+raw)
  f['conditions'][name]=b(key,raw,start=phrase+len(prefix))
 if family=='time-only': f['observed_at']=b(key,'2026-01-04',kind='date')
 rows[key]['facts'].append(f)
key='controls-v2/duplicate-citation-update';f=fact(key,'citation-X1','citation')
f['subject']=b(key,'X1');f['measurement_lineage']=b(key,'run-X1');rows[key]['facts'].append(f)
key='controls-v2/surviving-support-update'
for subject,status in (('X1','withdrawn'),('Y1','available')):
 f=fact(key,'availability-'+subject,'availability');f['subject']=b(key,subject);f['availability']=b(key,status)
 f['limitations'].append('Availability statement captured only; no runtime support withdrawal or independence judgment is applied.')
 rows[key]['facts'].append(f)

# Literal fields from the already exposed real graph report. No unit, missing
# environment, independent lineage or real answer-quality result is invented.
key='project-v1/graph-report';text=sources[key]['text'];report=json.loads(text)
measurement_cursor=text.index('"measurements"')
for mi,measurement in enumerate(report['measurements']):
 dataset_start=text.index('"dataset_version"',measurement_cursor)
 dataset_end=text.index('"dataset_sha256"',dataset_start)
 next_dataset=text.find('"dataset_version"',dataset_end)
 block_end=next_dataset if next_dataset>=0 else len(text)
 adapter_cursor=dataset_end
 for adapter,metrics in measurement['adapters'].items():
  adapter_start=text.index('"'+adapter+'"',adapter_cursor)
  adapter_cursor=adapter_start+len(adapter)+2
  for metric,values in metrics.items():
   if 'mean' not in values or values['mean'] is None: continue
   metric_start=text.index('"'+metric+'"',adapter_start)
   mean=re.search(r'"mean":\s*(-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?)',text[metric_start:block_end])
   sample=re.search(r'"n":\s*([0-9]+)',text[metric_start:block_end])
   f=fact(key,f'measurements/{mi}/{adapter}/{metric}/mean')
   f['subject']=b(key,adapter,start=adapter_start)
   f['metric']=dict(name=b(key,metric,start=metric_start),
       value=b(key,mean.group(1),start=metric_start+mean.start(1),kind='decimal'),unit=None,
       sample_count=b(key,sample.group(1),start=metric_start+sample.start(1),kind='decimal'))
   f['conditions']['workload']=b(key,measurement['dataset_version'],start=dataset_start)
   f['conditions']['corpus']=b(key,measurement['dataset_sha256'],start=dataset_end)
   f['conditions']['code']=b(key,report['source']['code_sha256'])
   f['conditions']['protocol']=b(key,report['method'])
   f['limitations'].extend(['Unit and environment absent from selected result fields; no comparability is inferred.',
                           'Report source_dirty is true; source commit alone is not the execution identity.',
                           'answer_correct_exact has no observed mean and is not converted to zero.'])
   rows[key]['facts'].append(f)
 measurement_cursor=block_end
packet=dict(schema='dm.development.observations/1',author=AUTHOR,exposure='previously-exposed-development-only',sources=list(rows.values()))
validate(packet,sources)
TRANSCRIPTIONS.write_text(json.dumps(packet,indent=2)+'\n')
print(json.dumps(dict(sources=len(rows),cases=len(cases),facts=sum(len(r['facts']) for r in rows.values()))))
