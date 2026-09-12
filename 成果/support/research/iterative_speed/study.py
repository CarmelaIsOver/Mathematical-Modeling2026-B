"""Small paired experiments, immutable per-round source/seed snapshots and logs."""
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
import argparse,hashlib,json,math,sys,time
import numpy as np
ROOT=Path(__file__).resolve().parent
SUPPORT=ROOT.parents[1]
sys.path.insert(0,str(SUPPORT))
from backend import LocalBackend
from audit import AuditPort
from variants import VARIANTS


def run_one(job):
    seed,problem,name,mode,trace_dir=job
    b=LocalBackend(seed,problem,error_mode='plus' if mode.endswith('plus') else 'minus' if mode.endswith('minus') else 'fixed',
                   radius=(1500 if mode.startswith('cluster_wide') else 1000) if mode!='normal' else None,n=16 if mode!='normal' else None,
                   all_directional=problem==4 and mode!='normal')
    if mode.startswith('cluster') or mode.startswith('boundary'):
        rng=np.random.default_rng(seed+715);angle=rng.uniform(0,2*math.pi)
        for i,s in enumerate(b.sources.values()):
            if mode.startswith('cluster'):s['p']=np.array([1100.,200.])+rng.uniform(-60,60,2)
            else:
                a=angle+2*math.pi*i/16;s['p']=1799.999*np.array([math.cos(a),math.sin(a)])
                if problem==4:s['direction']=a+math.pi/2
    port=AuditPort(b);base,kwargs=VARIANTS[problem][name]
    class Tracked(base):
        def __init__(self,*args,**kw):
            super().__init__(*args,**kw);self.phase='coverage'
            self.moves=dict(coverage=0.,localization=0.,clear=0.)
            self.no_signal=0;self.local_no_signal=0
        def locate(self,c):
            before=self.phase;self.phase='localization'
            try:return super().locate(c)
            finally:self.phase=before
        def action(self,path,p,c):
            distance=float(np.linalg.norm(np.asarray(p)-self.pos));phase='clear' if path=='/clear' else self.phase
            r=super().action(path,p,c);self.moves[phase]+=distance
            if path=='/measure' and r['measure_result']=='no_signal':
                self.no_signal+=1;self.local_no_signal+=int(self.phase=='localization')
            return r
    started=time.perf_counter();s=Tracked(port,problem,**kwargs);error=''
    try:
        result=s.run()
        assert all(c['vertex_bound_m']<=19.990001 for c in s.certificates)
        assert abs(sum(s.moves.values())-s.parts['move_s']*5)<1e-5
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc)
        result=dict(virtual_time_s=port.virtual_time,cleared=len(s.cleared),**s.counts,**s.parts)
    n=len(b.sources);complete=not error and port.exited and len(s.cleared)==n
    result.update(seed=seed,problem=problem,variant=name,mode=mode,full_clear=complete,total_targets=n,error=error,
                  mean_time_s=port.virtual_time/n,score_time_s=(port.virtual_time if complete else 360000)/n,
                  wall_s=time.perf_counter()-started,move_m=s.parts['move_s']*5,
                  phase_moves=s.moves,no_signal=s.no_signal,local_no_signal=s.local_no_signal)
    if trace_dir:Path(trace_dir,f'{name}_{seed}_{mode}.json').write_text(json.dumps({'metrics':result,'trace':b.trace}),encoding='utf-8')
    return result


def summarize(rows, control='baseline'):
    """Paired summary against an EXPLICIT control arm.

    The control must be named: for Q3 the strong arm is ``skip12_probe60``, not the
    legacy ``baseline`` (old off). Derived fields (gain/promising/tail_gate) are
    recomputed against this control and must not be consumed blindly.
    """
    baseline={(r['seed'],r['mode']):r for r in rows if r['variant']==control}
    assert baseline, f'control arm {control!r} not present in the round'
    out={}
    for name in sorted(set(r['variant'] for r in rows)):
        group=[r for r in rows if r['variant']==name];v=np.array([r['score_time_s'] for r in group])
        ratios=np.array([r['score_time_s']/baseline[r['seed'],r['mode']]['score_time_s'] for r in group])
        d={k:float(np.mean([r[k] for r in group])) for k in ['virtual_time_s','move_m','measure','failed_clear','fallback','wall_s','local_no_signal']}
        d.update(n=len(group),failures=sum(not r['full_clear'] for r in group),mean=float(v.mean()),
            p95=float(np.percentile(v,95)),p99=float(np.percentile(v,99)),cvar95=float(np.sort(v)[-max(1,math.ceil(.05*len(v))):].mean()),
            worst=float(v.max()),worst_ratio=float(ratios.max()),worst_seed=group[int(ratios.argmax())]['seed'],
            slower5=int((ratios>1.05).sum()),wins=int((ratios<1-1e-10).sum()),
            phases={p:float(np.mean([r['phase_moves'][p] for r in group])) for p in ['coverage','localization','clear']})
        out[name]=d
    ref=out[control]
    for n,d in out.items():
        d['gain']=1-d['mean']/ref['mean']
        d['promising']=d['failures']==0 and d['gain']>.02
        d['tail_gate']=d['failures']==0 and d['worst_ratio']<=1.05 and d['p95']<=ref['p95']
    return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--problem',type=int,required=True)
    ap.add_argument('--variants',nargs='+',required=True);ap.add_argument('--start',type=int,required=True)
    ap.add_argument('--count',type=int,default=24);ap.add_argument('--workers',type=int,default=4)
    ap.add_argument('--round',required=True);ap.add_argument('--hypothesis',required=True)
    ap.add_argument('--mode',default='normal');ap.add_argument('--traces',action='store_true')
    ap.add_argument('--control',default=None,
                    help='explicit control arm id; required when baseline is not the strong arm')
    a=ap.parse_args()
    if a.control is None:
        a.control='baseline' if 'baseline' in a.variants else a.variants[0]
    assert a.control in a.variants, f'--control {a.control!r} must be one of --variants'
    assert all(n in VARIANTS[a.problem] for n in a.variants)
    folder=ROOT/'results'/a.round;folder.mkdir(parents=True,exist_ok=False)
    snapshot={str(p.relative_to(SUPPORT)):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'source':p.read_text(encoding='utf-8-sig')}
              for p in [*SUPPORT.glob('*.py'),*ROOT.glob('*.py')]}
    (folder/'sources.json').write_text(json.dumps(snapshot,ensure_ascii=False),encoding='utf-8')
    (folder/'protocol.json').write_text(json.dumps(vars(a),ensure_ascii=False,indent=2),encoding='utf-8')
    traces=folder/'traces' if a.traces else None
    if traces:traces.mkdir()
    jobs=[(seed,a.problem,n,a.mode,str(traces) if traces else None) for seed in range(a.start,a.start+a.count) for n in a.variants]
    rows=[];started=time.perf_counter()
    with (folder/'metrics.jsonl').open('w',encoding='utf-8') as f,ProcessPoolExecutor(max_workers=a.workers) as pool:
        for i,future in enumerate(as_completed([pool.submit(run_one,j) for j in jobs]),1):
            r=future.result();rows.append(r);f.write(json.dumps(r)+'\n');f.flush()
            if i%24==0 or not r['full_clear']:print(i,len(jobs),round(time.perf_counter()-started,1),r['variant'],r['full_clear'],flush=True)
    summary=summarize(rows,a.control);(folder/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({n:{k:v[k] for k in ['mean','gain','p95','worst_ratio','failures']} for n,v in summary.items()}))


if __name__=='__main__':main()
