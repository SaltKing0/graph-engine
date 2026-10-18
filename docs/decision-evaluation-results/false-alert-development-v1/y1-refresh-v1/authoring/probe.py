import json,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from graph_engine.brain import Brain
from graph_engine.decision_service import DecisionService
from tools.decision_benchmark.support_paths import prepare,capture
sources,case,packet=prepare()
path=Path('/tmp/issue91-y1-refresh/probe-brain')
r=capture(path,sources,case,packet)
s=DecisionService(Brain(str(path),mode='git'))
report=dict(replay=r,comparisons={})
for name,before in [('initial',r['initial']['revision']),('withdrawal',r['comparison']['after']['revision']),('self',r['final']['revision'])]:
 comp=dict(schema='dm.compare/1',before=before,after=r['final']['revision'])
 out=s.compare(comp)
 report['comparisons'][name]=dict(input=comp,output=out,queue=s.read('review-queue',dict(comparison=comp,history=True)))
 print(name,'deltas',len(out['deltas']),'candidates',len(out['candidates']),'completeness',out['completeness'])
 for c in out['candidates']:
  print(c['delta']['event_id'],c['delta']['old'],c['delta']['new'], 'target', 'new' if c['target']==r['references']['decision'] else 'old' if c['target']==r['references']['old_decision'] else 'other',c['reasons'],'supports',len(c['support']['remaining']),len(c['support']['removed']),'id',c['candidate_id'])
report['detail']=s.read('review-detail',dict(reference=r['references']['finding']))
Path('/tmp/issue91-y1-refresh/probe.json').write_text(json.dumps(report,indent=2)+'\n')
