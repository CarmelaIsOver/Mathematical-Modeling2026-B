"""Q3 observation-only scheduling with complete seven-site coverage.

Known targets compete with remaining search sites in an estimated open route.
Waiting for three sites is not a reason to force a long trip. Once no search
sites remain, every known target is still mandatory and is cleared in turn.
"""
import time
import numpy as np
from solver import Solver
from joint_search import search_route


class OmniSearchSolver(Solver):
    def __init__(self,backend,problem,spacing=950.,max_refine=8,coverage_layout='original'):
        if problem!=3 or coverage_layout!='original':
            raise ValueError('Omni joint scheduling requires Q3 and original seven-site coverage')
        super().__init__(backend,problem,spacing,max_refine,coverage_layout=coverage_layout)
        self.diagnostics.update(skipped_known_measurements=0,route_replans=0)

    def skip_station_measurement(self,c,p):
        if c not in self.deferred:return False
        _,center,radius=self.region(c)
        # No claim that an unknown channel is absent is made here. Known
        # sources remain mandatory clearance tasks after their scan is skipped.
        return radius<=19.99 or np.linalg.norm(center-p)-radius>1500.

    def run(self):
        started=time.perf_counter();entered=self.api.enter()
        self.deadline=time.monotonic()+entered['remaining_real_duration_s']
        self.pending_stations=list(range(len(self.stations)))
        while self.pending_stations or self.deferred:
            self.deferred={c:age for c,age in self.deferred.items() if c not in self.cleared}
            if len(self.cleared)==16:break
            if self.deferred:
                keys=list(self.deferred)
                if not self.pending_stations:
                    c=min(keys,key=lambda c:np.linalg.norm(self.region(c)[1]-self.pos))
                    self.diagnostics['forced_targets']+=1
                    self.locate(c);self.deferred.pop(c,None)
                    continue
                nodes=[('target',c) for c in keys]+[('station',j) for j in self.pending_stations]
                points=np.array([self.region(c)[1] for c in keys]+[self.stations[j] for j in self.pending_stations])
                self.diagnostics['route_replans']+=1
                kind,which=nodes[search_route(points,self.pos)[0]]
                if kind=='target':
                    self.locate(which);self.deferred.pop(which,None)
                    continue
                i=which
            elif self.pending_stations:
                i=self.next_station()
            else:break
            self.pending_stations.remove(i);p=self.stations[i];found=[]
            channels=[c for c in range(1,21) if c not in self.cleared]
            if self.channel in channels:
                channels.remove(self.channel);channels.insert(0,self.channel)
            for c in channels:
                if self.skip_station_measurement(c,p):
                    self.diagnostics['skipped_known_measurements']+=1
                    continue
                result=self.action('/measure',p,c)['measure_result']
                if result=='near':
                    if not self.clear(p,c):raise RuntimeError('Near clear failed')
                elif result=='direction':found.append(c)
                if c in self.deferred:self.diagnostics['opportunistic_measures']+=1
            self.visited.append(i)
            for c in found:
                if c not in self.deferred:
                    self.deferred[c]=len(self.visited)
                    self.diagnostics['deferred_targets']+=1
            if len(self.cleared)==16:break
        if len(self.cleared)<16 and (self.pending_stations or any(c not in self.cleared for c in self.deferred)):
            raise RuntimeError('Cannot finish with unresolved coverage or targets')
        exited=self.api.exit()
        if exited.get('accepted') is not True or exited.get('exit_reason')!='user_exit':
            raise RuntimeError('Normal exit not acknowledged')
        total=self.api.virtual_time
        return dict(problem=self.problem,complete=True,cleared=len(self.cleared),virtual_time_s=total,
            mean_time_s=total/len(self.cleared) if self.cleared else None,
            program_time_s=time.perf_counter()-started,stations_visited=len(self.visited),
            scheduling_policy='joint_route',**self.counts,**self.parts,**self.diagnostics)
