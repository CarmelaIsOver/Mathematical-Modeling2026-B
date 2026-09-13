"""Q4 joint coverage/localization routing, using acknowledged observations only.

The covering mesh and mandatory resolution of discovered sources ensure
completion. Route search and the single small-region optical probe are cost
heuristics, not promises of optimality or of a 400-second per-source score.
"""
import time
import numpy as np
from active_localization import ActiveLocalizationSolver
from localization_service import LocalizationService


def search_route(points,start):
    """Eight nearest-neighbor starts with best-improvement open-path 2-opt."""
    points=np.asarray(points);n=len(points)
    if not n:return []
    all_points=np.vstack([points,start,start])
    distances=np.linalg.norm(all_points[:,None,:]-all_points[None,:,:],axis=2)
    distances[n+1,:]=0.;distances[:,n+1]=0.
    best=[];best_cost=float('inf')
    for first in np.argsort(distances[n,:n])[:min(8,n)]:
        remaining=set(range(n));remaining.remove(int(first));order=[int(first)]
        while remaining:
            j=min(remaining,key=lambda j:(distances[order[-1],j],j))
            order.append(j);remaining.remove(j)
        route=np.array([n]+order+[n+1])
        for _ in range(50):
            a=route[:-1];b=route[1:]
            delta=(distances[a[:,None],a[None,:]]+distances[b[:,None],b[None,:]]
                   -distances[a,b][:,None]-distances[a,b][None,:])
            delta[np.tril_indices(n+1,1)]=np.inf
            i,j=np.unravel_index(np.argmin(delta),delta.shape)
            if delta[i,j]>=-1e-7:break
            route[i+1:j+1]=route[i+1:j+1][::-1]
        cost=distances[route[:-1],route[1:]].sum()
        if cost<best_cost:best=route[1:-1].tolist();best_cost=cost
    return best


class JointSearchSolver(ActiveLocalizationSolver):
    def __init__(self,backend,problem,spacing=950.,max_refine=8,coverage_layout='radial',service_policy='atomic'):
        if problem!=4 or spacing!=950. or coverage_layout not in ('radial','rings'):
            raise ValueError('Joint search requires Q4 and a verified directional coverage layout')
        self.coverage_layout=coverage_layout
        super().__init__(backend,problem,spacing,max_refine,coverage_layout=coverage_layout)
        if service_policy not in ('atomic','adaptive'):raise ValueError('Unknown service policy')
        self.service_policy=service_policy
        self._localization_service=LocalizationService(self)
        self.diagnostics.update(route_replans=0,skipped_known_measurements=0,
                                small_region_probes=0,small_region_successes=0,
                                coverage_sites_cancelled=0)
        if service_policy=='adaptive':self.diagnostics.update(service_steps=0,service_resumes=0)

    def locate(self,c):
        _,center,radius=self.region(c)
        if 19.99<radius<=40.:
            # A cheap attempt along the planned visit. Failure never certifies
            # clearance or shrinks the feasible set; refinement still follows.
            self.diagnostics['small_region_probes']+=1
            if self.clear(center,c):
                self.diagnostics['small_region_successes']+=1
                return
        return super().locate(c)

    def skip_known_measurement(self,c,p):
        if c not in self.deferred:return False
        _,center,radius=self.region(c)
        return (radius<=19.99 or np.linalg.norm(p-center)-radius>1500.
                or (len(self.obs[c])>=2 and radius<=40.))

    def run(self):
        started=time.perf_counter();entered=self.api.enter()
        self.deadline=time.monotonic()+entered['remaining_real_duration_s']
        self.pending_stations=list(range(len(self.stations)))
        while self.pending_stations or self.deferred:
            self.deferred={c:age for c,age in self.deferred.items() if c not in self.cleared}
            if len(self.cleared)==16:break
            known=list(self.deferred)
            if self.coverage_layout=='rings' and len(known)+len(self.cleared)==16:
                # The stated upper bound has been reached using observations.
                # Unknown-channel discovery is finished, clearance is not.
                self.diagnostics['coverage_sites_cancelled']+=len(self.pending_stations)
                self.pending_stations=[]
            points=[self.region(c)[1] for c in known]+[self.stations[i] for i in self.pending_stations]
            nodes=[('target',c) for c in known]+[('station',i) for i in self.pending_stations]
            if not nodes:break
            self.diagnostics['route_replans']+=1
            kind,index=nodes[search_route(points,self.pos)[0]]
            if kind=='target':
                if self.service_policy=='adaptive':self._localization_service.advance_directional(index)
                else:self.locate(index)
                continue
            self.pending_stations.remove(index);p=self.stations[index]
            channels=[c for c in range(1,21) if c not in self.cleared]
            if self.channel in channels:
                channels.remove(self.channel);channels.insert(0,self.channel)
            for c in channels:
                if self.skip_known_measurement(c,p):
                    self.diagnostics['skipped_known_measurements']+=1
                    continue
                result=self.action('/measure',p,c)['measure_result']
                if result=='near':
                    if not self.clear(p,c):raise RuntimeError('Near clear failed')
                elif result=='direction' and c not in self.deferred:
                    self.deferred[c]=len(self.visited)+1
                    self.diagnostics['deferred_targets']+=1
            self.visited.append(index)
        if len(self.cleared)<16 and (self.pending_stations or any(c not in self.cleared for c in self.deferred)):
            raise RuntimeError('Unresolved coverage or targets')
        exited=self.api.exit()
        if exited.get('accepted') is not True or exited.get('exit_reason')!='user_exit':
            raise RuntimeError('Normal exit not acknowledged')
        total=self.api.virtual_time
        return dict(problem=self.problem,complete=True,cleared=len(self.cleared),
                    virtual_time_s=total,mean_time_s=total/len(self.cleared) if self.cleared else None,
                    stations_visited=len(self.visited),program_time_s=time.perf_counter()-started,
                    **self.counts,**self.parts,**self.diagnostics)
