"""Q3 observation-only scheduling with complete seven-site coverage.

Known targets compete with remaining search sites in an estimated open route.
Waiting for three sites is not a reason to force a long trip. Once no search
sites remain, every known target is still mandatory and is cleared in turn.
"""
import time
import numpy as np
from geometry import optical_cover, feasible, enclosing_circle
from solver import Solver, open_route
from joint_search import search_route
from negative_observations import apply_negative_halfplanes


class OmniSearchSolver(Solver):
    def __init__(self,backend,problem,spacing=950.,max_refine=8,coverage_layout='original',
                 negative_observations=False,certify_on_tight=False,negative_route=False):
        if problem!=3 or coverage_layout!='original':
            raise ValueError('Omni joint scheduling requires Q3 and original seven-site coverage')
        super().__init__(backend,problem,spacing,max_refine,coverage_layout=coverage_layout)
        # Optional Q3 positive/negative bisector constraints. Off by default so the
        # team's joint scheduler stays the untouched production baseline.
        self.use_negatives=bool(negative_observations)
        self.certify_on_tight=bool(certify_on_tight) and self.use_negatives
        # By default the tightened bound only ranks the next measurement; route
        # centres, station-scan skips and clearance certificates stay on the
        # positive-reception outer bound. negative_route=True also lets the
        # tightened bound drive routing (pilot showed it adds tail regressions).
        self.negative_route=bool(negative_route)
        self.negatives={c:[] for c in self.obs}
        self.outer_cache={}
        self.region_updates=[]
        self.diagnostics.update(skipped_known_measurements=0,route_replans=0,
                                negative_observations=0,negative_region_fallbacks=0,
                                negative_constraints=0)

    def action(self,path,p,c):
        response=super().action(path,p,c)
        if (self.use_negatives and path=='/measure'
                and response['measure_result']=='no_signal' and c not in self.cleared):
            # A not-received reading is retained even before the source is found.
            self.negatives[c].append(self.pos.copy())
            self.diagnostics['negative_observations']+=1
        return response

    def outer_region(self,c):
        """Positive-reception outer bound; always a valid enclosing region."""
        n=len(self.obs[c])
        if c not in self.outer_cache or self.outer_cache[c][0]!=n:
            poly=feasible(self.obs[c])
            if not len(poly):
                raise ValueError('Empty positive feasible region')
            center,radius=enclosing_circle(poly)
            self.outer_cache[c]=(n,poly,center,radius)
        return self.outer_cache[c][1:]

    def region(self,c):
        if not self.use_negatives:
            return super().region(c)
        return self.tight_region(c) if self.negative_route else self.outer_region(c)

    def tight_region(self,c):
        """Received/not-received tightened bound; planning use only by default."""
        key=(len(self.obs[c]),len(self.negatives[c]))
        if c not in self.cache or self.cache[c][0]!=key:
            outer,_,_=self.outer_region(c)
            poly,count=apply_negative_halfplanes(outer,self.obs[c],self.negatives[c])
            if not len(poly) or not np.all(np.isfinite(poly)):
                # Numerical fail-safe preserves the complete outer bound and completeness.
                poly=outer
                self.diagnostics['negative_region_fallbacks']+=1
            center,radius=enclosing_circle(poly)
            self.cache[c]=(key,poly,center,radius)
            self.diagnostics['negative_constraints']+=count
            self.region_updates.append({'channel':c,'positive_count':key[0],
                'negative_count':key[1],'constraints':count,
                'before_radius':self.outer_cache[c][3],'after_radius':radius,
                'position':self.pos.tolist()})
        return self.cache[c][1:]

    def _certificate_region(self,c):
        """Region whose clearance certificate must hold.

        Default keeps the certificate on the positive-reception outer bound, so
        a negative half-plane may guide planning but never authorise a clear.
        """
        if self.certify_on_tight:
            return self.tight_region(c)
        return self.outer_region(c)

    def locate(self,c):
        if not self.use_negatives:
            return super().locate(c)
        dark=0
        for _ in range(self.max_refine):
            cert_poly,cert_center,cert_radius=self._certificate_region(c)
            if cert_radius<=19.99:
                self.certified_clear(c,cert_poly,cert_center,cert_radius)
                return
            # Only the tightened region ranks the next measurement.
            poly,center,radius=self.tight_region(c)
            q=self.next_measure(c,poly,center,radius)
            if q is None:
                break
            r=self.action('/measure',q,c)
            if r['measure_result']=='near':
                if not self.clear(self.pos,c):
                    raise RuntimeError('Near clear failed')
                return
            if r['measure_result']=='no_signal':
                dark+=1
                if dark>=2:
                    break
            else:
                dark=0
        cert_poly,cert_center,cert_radius=self._certificate_region(c)
        if cert_radius<=19.99:
            self.certified_clear(c,cert_poly,cert_center,cert_radius)
            return
        self.counts['fallback']+=1
        points=optical_cover(cert_poly,self.obs[c][0][1])
        points=points[open_route(points,self.pos)]
        for p in points:
            if self.clear(p,c):
                return
        raise RuntimeError('Exhausted optical cover')

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
