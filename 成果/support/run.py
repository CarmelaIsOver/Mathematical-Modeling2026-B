"""One entry point for the maintained controller and local experiments."""
import argparse,csv,json,time
from pathlib import Path
from backend import HTTPBackend,LocalBackend,health_check
from solver import Solver
from audit import AuditPort

ROOT=Path(__file__).resolve().parent


def main():
    ap=argparse.ArgumentParser(description='Radio-source search and clearance')
    ap.add_argument('--mode',choices=['offline','official'],default='offline')
    ap.add_argument('--problem',type=int,choices=[3,4],default=3)
    ap.add_argument('--strategy',choices=['standard','paper','integrated'],default=None,
                    help='default: integrated scheduling for both Q3 and Q4')
    ap.add_argument('--layout',choices=['original','compact','radial','rings'],default=None,
                    help='default: radial for integrated Q4, original otherwise')
    ap.add_argument('--robot-id');ap.add_argument('--url',default='http://127.0.0.1:2026')
    ap.add_argument('--http-health-probe',action='store_true',
                    help='opt-in: TCP reachability check before the session starts (official mode only)')
    ap.add_argument('--runs',type=int,default=1);ap.add_argument('--seed',type=int,default=20260910)
    ap.add_argument('--spacing',type=float,default=950.);ap.add_argument('--refine',type=int,default=8)
    ap.add_argument('--error',choices=['fixed','plus','minus'],default='fixed')
    ap.add_argument('--radius',type=float);ap.add_argument('--all-directional',action='store_true')
    ap.add_argument('--negative-observations',action='store_true',
                    help='Q3 integrated only: received/not-received bisector constraints (opt-in, default off)')
    ap.add_argument('--q3-ring-guard',choices=['off','aggressive','conservative'],default='off',
                    help='Q3 integrated only: guarded 1123m seven-site ring shrink (opt-in, default off)')
    ap.add_argument('--q4-probe-radius',type=float,default=40.,
                    help='Q4 integrated only: optical probe window upper bound in metres '
                         '(default 40; <=19.99 disables the probe; opt-in)')
    ap.add_argument('--q3-probe-radius',type=float,default=0.,
                    help='Q3 integrated only: optical probe when the feasible region radius is at '
                         'most this value (metres; 0 or negative disables it; opt-in, default off)')
    ap.add_argument('--output',default=None)
    a=ap.parse_args()
    if a.strategy is None:a.strategy='integrated'
    if a.layout is None:a.layout='radial' if a.strategy=='integrated' and a.problem==4 else 'original'
    if a.negative_observations and not (a.strategy=='integrated' and a.problem==3):
        ap.error('--negative-observations requires --strategy integrated --problem 3')
    if a.q3_ring_guard!='off' and not (a.strategy=='integrated' and a.problem==3):
        ap.error('--q3-ring-guard requires --strategy integrated --problem 3')
    if a.q3_probe_radius>0 and not (a.strategy=='integrated' and a.problem==3):
        ap.error('--q3-probe-radius requires --strategy integrated --problem 3')
    if 0<a.q3_probe_radius<=19.99:
        ap.error('--q3-probe-radius must exceed the certified radius 19.99')
    if a.q4_probe_radius!=40. and not (a.strategy=='integrated' and a.problem==4):
        ap.error('--q4-probe-radius requires --strategy integrated --problem 4')
    if a.strategy=='integrated':
        required_layouts=('radial','rings') if a.problem==4 else ('original',)
        if a.layout not in required_layouts or a.spacing!=950.:
            ap.error('Integrated scheduling requires the problem-specific default layout and 950m spacing')
        if a.problem==4:
            from joint_search import JointSearchSolver
            controller=JointSearchSolver
        else:
            from omni_search import OmniSearchSolver
            controller=OmniSearchSolver
    elif a.strategy=='paper':
        from active_localization import ActiveLocalizationSolver
        controller=ActiveLocalizationSolver
    else:controller=Solver
    if a.mode=='official' and not a.robot_id:ap.error('--robot-id is required')
    if a.http_health_probe and a.mode!='official':ap.error('--http-health-probe requires --mode official')
    if a.runs<1:ap.error('--runs must be positive')
    if a.layout in ('compact','radial','rings') and (a.problem!=4 or a.spacing!=950.):
        ap.error('Optimized layouts require --problem 4 and the default 950m spacing')
    if a.mode=='official' and (a.runs!=1 or a.spacing!=950 or a.refine!=8):
        ap.error('Official runs use the maintained default policy; tuning flags are offline only')
    out=Path(a.output) if a.output else ROOT/('practice_logs' if a.mode=='official' else 'results')
    out.mkdir(parents=True,exist_ok=True)
    stamp=time.strftime('%Y%m%d_%H%M%S')+'_'+str(time.time_ns()%1000000000)
    rows=[]
    print(f'Starting Q{a.problem}: strategy={a.strategy}, mode={a.mode}, layout={a.layout}',flush=True)
    for i in range(1 if a.mode=='official' else a.runs):
        stem=out/f'client_q{a.problem}_{stamp}_{i+1}'
        if a.mode=='official' and a.http_health_probe:
            health_check(a.url)
        backend=(HTTPBackend(a.robot_id,a.url,stem.with_suffix('.jsonl')) if a.mode=='official'
                 else LocalBackend(a.seed+i,a.problem,a.error,a.radius,all_directional=a.all_directional))
        port=AuditPort(backend)
        try:
            kwargs={'coverage_layout':a.layout}
            if a.negative_observations:kwargs['negative_observations']=True
            if a.q3_ring_guard!='off':kwargs['ring_guard']=a.q3_ring_guard
            if a.q3_probe_radius>0:kwargs['probe_radius']=a.q3_probe_radius
            if a.problem==4 and a.q4_probe_radius!=40.:kwargs['probe_radius']=a.q4_probe_radius
            r=controller(port,a.problem,a.spacing,a.refine,**kwargs).run()
            r['strategy']=a.strategy
            r['coverage_layout']=a.layout
            r['negative_observations']=bool(a.negative_observations)
            r['q3_ring_guard']=a.q3_ring_guard
            r['q3_probe_radius']=a.q3_probe_radius
            r['q4_probe_radius']=a.q4_probe_radius
            r.update(normal_exit=port.exited,max_step_time_error_s=port.max_step_error_s,**port.parts)
            r['provenance']='Official HTTP interface; case code and module come from simulator UI'
            if a.mode=='offline':
                r.update(seed=a.seed+i,total=len(backend.sources),ratio=r['cleared']/len(backend.sources),
                         provenance='LOCAL_SYNTHETIC',spacing=a.spacing,error=a.error,
                         directional=sum(s['direction'] is not None for s in backend.sources.values()))
                assert r['cleared']==len(backend.sources)
                if i==0:
                    truth={c:{k:(v.tolist() if hasattr(v,'tolist') else v) for k,v in s.items()} for c,s in backend.sources.items()}
                    (out/f'local_q{a.problem}_example.json').write_text(json.dumps({'sources':truth,'trace':backend.trace},indent=2),encoding='utf-8')
            else:stem.with_suffix('.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
            rows.append(r)
            if a.mode=='official' or a.runs==1:print(json.dumps(r,indent=2),flush=True)
            else:print(f'LOCAL Q{a.problem} seed={a.seed+i} cleared={r["cleared"]}/{r["total"]} mean={r["mean_time_s"]:.3f}',flush=True)
        except Exception as exc:
            failed={'complete':False,'normal_exit':port.exited,'problem':a.problem,
                    'strategy':a.strategy,
                    'coverage_layout':a.layout,
                    'last_acknowledged_virtual_time_s':port.virtual_time,
                    'error':type(exc).__name__+': '+str(exc)}
            stem.with_suffix('.error.json').write_text(json.dumps(failed,indent=2),encoding='utf-8')
            raise
        finally:
            if hasattr(backend,'log'):backend.log.close()
    if a.mode=='offline':
        with (out/f'local_q{a.problem}.csv').open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

if __name__=='__main__':main()
