"""One entry point for the maintained controller and local experiments."""
import argparse,csv,json,time
from pathlib import Path
from backend import HTTPBackend,LocalBackend
from solver import Solver
from audit import AuditPort

ROOT=Path(__file__).resolve().parent


def main():
    ap=argparse.ArgumentParser(description='Radio-source search and clearance')
    ap.add_argument('--mode',choices=['offline','official'],default='offline')
    ap.add_argument('--problem',type=int,choices=[3,4],default=3)
    ap.add_argument('--strategy',choices=['standard','paper','integrated'],default=None,
                    help='default: integrated scheduling for both Q3 and Q4')
    ap.add_argument('--layout',choices=['original','compact','radial','rings','tight','hex'],default=None,
                    help='default: original with guarded ring for Q3, rings for adaptive Q4, radial for atomic Q4')
    ap.add_argument('--service-policy',choices=['atomic','adaptive'],default=None,
                    help='integrated Q4: adaptive (default) or atomic; Fusion Q3 uses atomic only')
    ap.add_argument('--q3-ring-guard',choices=['off','aggressive','conservative'],default=None,
                    help='integrated Q3 only: default aggressive (Fusion recommended)')
    ap.add_argument('--q3-probe-radius',type=float,default=None,
                    help='integrated Q3 only: default 60m; 0 disables the optical probe')
    ap.add_argument('--negative-observations',action='store_true',
                    help='integrated Q3 only: optional negative half-plane planning (default off)')
    ap.add_argument('--robot-id');ap.add_argument('--url',default='http://127.0.0.1:2026')
    ap.add_argument('--runs',type=int,default=1);ap.add_argument('--seed',type=int,default=20260910)
    ap.add_argument('--spacing',type=float,default=950.);ap.add_argument('--refine',type=int,default=8)
    ap.add_argument('--error',choices=['fixed','plus','minus'],default='fixed')
    ap.add_argument('--radius',type=float);ap.add_argument('--all-directional',action='store_true')
    ap.add_argument('--output',default=None)
    a=ap.parse_args()
    if a.strategy is None:a.strategy='integrated'
    if a.strategy!='integrated' and a.service_policy is not None:
        ap.error('--service-policy is only available for integrated scheduling')
    q3_integrated=a.problem==3 and a.strategy=='integrated'
    if not q3_integrated and (a.q3_ring_guard is not None or a.q3_probe_radius is not None or a.negative_observations):
        ap.error('Q3 options require --problem 3 --strategy integrated')
    if q3_integrated:
        if a.service_policy=='adaptive':ap.error('Fusion Q3 uses atomic localization; omit --service-policy')
        a.service_policy='atomic'
        if a.q3_ring_guard is None:a.q3_ring_guard='aggressive'
        if a.q3_probe_radius is None:a.q3_probe_radius=60.
        if not (a.q3_probe_radius==0 or 19.99<a.q3_probe_radius<float('inf')):
            ap.error('--q3-probe-radius must be 0 or a finite value greater than 19.99')
    if a.strategy=='integrated' and a.service_policy is None:a.service_policy='adaptive'
    if a.layout is None:
        # Q3 uses the user-requested Fusion policy. Q4 selection is unchanged.
        q4_layout='rings' if a.service_policy=='adaptive' else 'radial'
        q3_layout='original'
        a.layout=(q4_layout if a.problem==4 else q3_layout) if a.strategy=='integrated' else 'original'
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
    if a.runs<1:ap.error('--runs must be positive')
    if a.layout in ('compact','radial','rings') and (a.problem!=4 or a.spacing!=950.):
        ap.error('Optimized layouts require --problem 4 and the default 950m spacing')
    if a.layout in ('tight','hex') and a.problem!=3:
        ap.error('Omni ring layouts are certified for Q3 only')
    if a.mode=='official' and (a.runs!=1 or a.spacing!=950 or a.refine!=8):
        ap.error('Official runs use the maintained default policy; tuning flags are offline only')
    out=Path(a.output) if a.output else ROOT/('practice_logs' if a.mode=='official' else 'results')
    out.mkdir(parents=True,exist_ok=True)
    stamp=time.strftime('%Y%m%d_%H%M%S')+'_'+str(time.time_ns()%1000000000)
    rows=[]
    policy_label=f', service_policy={a.service_policy}' if a.strategy=='integrated' else ''
    if q3_integrated:policy_label+=f', ring_guard={a.q3_ring_guard}, probe_radius={a.q3_probe_radius:g}'
    print(f'Starting Q{a.problem}: strategy={a.strategy}, mode={a.mode}, layout={a.layout}{policy_label}',flush=True)
    for i in range(1 if a.mode=='official' else a.runs):
        stem=out/f'client_q{a.problem}_{stamp}_{i+1}'
        backend=(HTTPBackend(a.robot_id,a.url,stem.with_suffix('.jsonl')) if a.mode=='official'
                 else LocalBackend(a.seed+i,a.problem,a.error,a.radius,all_directional=a.all_directional))
        port=AuditPort(backend)
        try:
            policy_args={'service_policy':a.service_policy} if a.strategy=='integrated' else {}
            if q3_integrated:policy_args=dict(ring_guard=a.q3_ring_guard,probe_radius=a.q3_probe_radius,negative_observations=a.negative_observations)
            r=controller(port,a.problem,a.spacing,a.refine,coverage_layout=a.layout,**policy_args).run()
            r['strategy']=a.strategy
            r['coverage_layout']=a.layout
            if a.strategy=='integrated':r['service_policy']=a.service_policy
            if q3_integrated:r.update(q3_ring_guard=a.q3_ring_guard,q3_probe_radius=a.q3_probe_radius,use_negative_observations=a.negative_observations)
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
                    'service_policy':a.service_policy,
                    'last_acknowledged_virtual_time_s':port.virtual_time,
                    'error':type(exc).__name__+': '+str(exc)}
            if q3_integrated:failed.update(q3_ring_guard=a.q3_ring_guard,q3_probe_radius=a.q3_probe_radius,use_negative_observations=a.negative_observations)
            stem.with_suffix('.error.json').write_text(json.dumps(failed,indent=2),encoding='utf-8')
            raise
        finally:
            if hasattr(backend,'log'):backend.log.close()
    if a.mode=='offline':
        with (out/f'local_q{a.problem}.csv').open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

if __name__=='__main__':main()
