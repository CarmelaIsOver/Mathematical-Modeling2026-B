"""Reproducible stress and sensitivity experiments; never official results."""
import csv
import json
from pathlib import Path
import numpy as np
from backend import LocalBackend
from solver import Solver
from audit import AuditPort

def run_batch(out,name,problem,seeds,**kwargs):
    rows=[]
    for seed in seeds:
        local={k:kwargs[k] for k in ['error_mode','radius','all_directional'] if k in kwargs}
        b=LocalBackend(seed,problem,**local)
        # Additional deterministic boundary/tangent scenarios.
        if name.startswith('boundary'):
            for i,s in enumerate(b.sources.values()):
                angle=2*np.pi*i/len(b.sources)
                s['p']=1800*np.array([np.cos(angle),np.sin(angle)])
                s['radius']=1000.
                s['direction']=angle if seed%2 else angle+np.pi/2
        solve={k:kwargs[k] for k in ['spacing','max_refine'] if k in kwargs}
        port=AuditPort(b)
        r=Solver(port,problem,**solve).run()
        r.update(seed=seed,total=len(b.sources),ratio=r['cleared']/len(b.sources),
                 experiment=name,provenance='LOCAL_SYNTHETIC',normal_exit=port.exited,**b.parts)
        assert r['ratio']==1,r
        rows.append(r)
    with (out/(name+'.csv')).open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    result=dict(experiment=name,runs=len(rows),cleared=sum(r['cleared'] for r in rows),
          total=sum(r['total'] for r in rows),mean_time_s=float(np.mean([r['mean_time_s'] for r in rows])),
          weighted_mean_s=sum(r['virtual_time_s'] for r in rows)/sum(r['cleared'] for r in rows),
          max_mean_s=max(r['mean_time_s'] for r in rows),fallback=sum(r['fallback'] for r in rows))
    print(json.dumps(result),flush=True)
    return result

def main():
    out=Path('results/stress');out.mkdir(parents=True,exist_ok=True)
    summary=[]
    for p in (3,4):
        for error in ('plus','minus'):
            summary.append(run_batch(out,f'q{p}_{error}_r1000',p,range(100,120),
                          error_mode=error,radius=1000.,all_directional=True))
    summary.append(run_batch(out,'boundary_outward_tangent',4,range(20,40),all_directional=True))
    for h in (800,900,950,999):
        summary.append(run_batch(out,f'q4_spacing_{h}',4,range(200,220),spacing=h))
    for p in (3,4):
        summary.append(run_batch(out,f'q{p}_optical_only',p,range(20260910,20260920),max_refine=0))
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')

if __name__=='__main__':
    main()
