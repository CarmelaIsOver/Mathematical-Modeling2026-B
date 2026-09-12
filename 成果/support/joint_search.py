"""Q4 joint coverage/localization routing, using acknowledged observations only.

The covering mesh and mandatory resolution of discovered sources ensure
completion. Route search and the single small-region optical probe are cost
heuristics, not promises of optimality or of a 400-second per-source score.
"""
import time
import numpy as np
from active_localization import ActiveLocalizationSolver
from coverage_geometry import layout_cells, cell_is_covered


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
    def __init__(self,backend,problem,spacing=950.,max_refine=8,coverage_layout='radial',
                 reschedule_after_step=False,target_measure_budget=None,step_skip_known=False,
                 close_discovery_on_upper_bound=True,certify_channel_absence=False,
                 reschedule_switches=None,probe_radius=40.,skip_tight_radius=40.):
        if problem!=4 or spacing!=950. or coverage_layout not in ('radial','rings'):
            raise ValueError('Joint search requires Q4 and a verified directional coverage layout')
        self.coverage_layout=coverage_layout
        super().__init__(backend,problem,spacing,max_refine,coverage_layout=coverage_layout)
        self.diagnostics.update(route_replans=0,skipped_known_measurements=0,
                                small_region_probes=0,small_region_successes=0,
                                coverage_sites_cancelled=0,rescheduled_targets=0,
                                reschedule_steps=0,reschedule_fallbacks=0,discovery_closed=0,
                                channels_certified_absent=0,absence_skipped_measurements=0,
                                discovery_closed_by_absence=0,reschedule_bursts=0)
        # Opt-in: end a scheduling turn after one region-updating measurement.
        # Measurement budget is per channel and never reset by re-planning.
        self.reschedule_after_step=bool(reschedule_after_step)
        self.target_measure_budget=max_refine if target_measure_budget is None else int(target_measure_budget)
        self.target_measures={}
        self.small_probe_state={}
        # Opt-in window for the small-region optical probe. The certified path is
        # unchanged: only the radius bound that decides when a probe is attempted
        # moves. Values <=19.99 disable the probe entirely (research isolation).
        self.probe_radius=float(probe_radius)
        # Radius below which a known target with >=2 bearings is no longer worth
        # an opportunistic station measurement (default 40 keeps the baseline).
        self.skip_tight_radius=float(skip_tight_radius)
        # Optional bound on how often a target returns to the scheduler. Once the
        # allowed returns are used, the target is finished without interruption,
        # which keeps the first re-decision but stops repeated interleaving.
        self.reschedule_switches=None if reschedule_switches is None else int(reschedule_switches)
        self.target_switches={}
        # When stepping, a station pass must not duplicate a target's dedicated
        # measurements; open targets are resolved by their own turns instead.
        self.step_skip_known=bool(step_skip_known)
        self.close_discovery_on_upper_bound=bool(close_discovery_on_upper_bound)
        # Once the stated upper bound is reached from acknowledged observations,
        # no unknown channel can still hold a source. Discovery obligations end;
        # unvisited stations stay available only as optional localization points.
        self.discovery_closed=False
        # Opt-in per-channel coverage certificate: a channel that was measured
        # with no signal at every station of a certified mesh cell cannot hold a
        # source in that cell. Only genuine measurement positions count.
        self.certify_channel_absence=bool(certify_channel_absence)
        self.absent_channels=set()
        if self.certify_channel_absence:
            (self.cell_masks,self.cell_sizes,self.station_cells,
             self.cell_centers,self.cell_halves)=layout_cells(self.stations)
            n=len(self.cell_masks)
            self.cell_ok={c:np.zeros(n,dtype=bool) for c in range(1,21)}
            self.station_scanned={c:np.zeros(len(self.stations),dtype=bool)
                                  for c in range(1,21)}

    def locate(self,c):
        if not self.reschedule_after_step:
            return self._locate_full(c)
        if self._small_region_probe(c):
            return
        if self.target_measures.get(c,0)>=self.target_measure_budget:
            # Budget spent: finish the target as one uninterrupted fallback.
            self.diagnostics['reschedule_fallbacks']+=1
            return self.directional_fallback(c)
        if (self.reschedule_switches is not None
                and self.target_switches.get(c,0)>=self.reschedule_switches):
            self.diagnostics['reschedule_bursts']+=1
            return self._locate_burst(c)
        status=self.directional_step(c)
        self.target_measures[c]=self.target_measures.get(c,0)+1
        self.diagnostics['reschedule_steps']+=1
        if status=='cleared':
            return
        if status=='no_progress':
            self.diagnostics['reschedule_fallbacks']+=1
            return self.directional_fallback(c)
        # 'open': return to the scheduler so the next turn sees the new region.
        self.diagnostics['rescheduled_targets']+=1
        self.target_switches[c]=self.target_switches.get(c,0)+1
        return None

    def _locate_burst(self,c):
        """Finish a target without returning to the scheduler."""
        while self.target_measures.get(c,0)<self.target_measure_budget:
            status=self.directional_step(c)
            self.target_measures[c]=self.target_measures.get(c,0)+1
            self.diagnostics['reschedule_steps']+=1
            if status=='cleared':
                return
            if status=='no_progress':
                break
        self.diagnostics['reschedule_fallbacks']+=1
        return self.directional_fallback(c)

    def _locate_full(self,c):
        _,center,radius=self.region(c)
        if 19.99<radius<=self.probe_radius:
            # A cheap attempt along the planned visit. Failure never certifies
            # clearance or shrinks the feasible set; refinement still follows.
            self.diagnostics['small_region_probes']+=1
            if self.clear(center,c):
                self.diagnostics['small_region_successes']+=1
                return
        return super().locate(c)

    def _small_region_probe(self,c):
        """Small-region optical probe, attempted once per region state.

        Returns True when the probe cleared the channel. A failed probe is not
        repeated until a new observation changes the region, so re-planning
        cannot re-run the same trial.
        """
        _,center,radius=self.region(c)
        if not 19.99<radius<=self.probe_radius:
            return False
        state=len(self.obs[c])
        if self.small_probe_state.get(c)==state:
            return False
        self.small_probe_state[c]=state
        self.diagnostics['small_region_probes']+=1
        if self.clear(center,c):
            self.diagnostics['small_region_successes']+=1
            return True
        return False

    def _note_silent(self,c,station_index):
        """Record a genuine no-signal position in the per-channel certificate."""
        self.station_scanned[c][station_index]=True
        ok=self.cell_ok[c]
        total=len(self.stations)
        for j in self.station_cells[station_index]:
            if ok[j]:continue
            mask=self.cell_masks[j]
            sensors=[self.stations[k] for k in range(total)
                     if (mask>>k)&1 and self.station_scanned[c][k]]
            if cell_is_covered(self.cell_centers[j],self.cell_halves[j],sensors):
                ok[j]=True
        if c not in self.deferred and c not in self.cleared and bool(np.all(ok)):
            self.absent_channels.add(c)
            self.diagnostics['channels_certified_absent']+=1

    def _station_channel_unneeded(self,station_index,c):
        """True when measuring c at this station covers no uncertified cell."""
        return all(self.cell_ok[c][j] for j in self.station_cells[station_index])

    def skip_known_measurement(self,c,p):
        if c not in self.deferred:return False
        if self.reschedule_after_step and self.step_skip_known:
            return True
        _,center,radius=self.region(c)
        return (radius<=19.99 or np.linalg.norm(p-center)-radius>1500.
                or (len(self.obs[c])>=2 and radius<=self.skip_tight_radius))

    def run(self):
        started=time.perf_counter();entered=self.api.enter()
        self.deadline=time.monotonic()+entered['remaining_real_duration_s']
        self.pending_stations=list(range(len(self.stations)))
        while self.pending_stations or self.deferred:
            self.deferred={c:age for c,age in self.deferred.items() if c not in self.cleared}
            if len(self.cleared)==16:break
            known=list(self.deferred)
            discovered=len(known)+len(self.cleared)
            if (self.close_discovery_on_upper_bound and not self.discovery_closed
                    and (discovered==16 or discovered+len(self.absent_channels)==20)):
                # The stated upper bound has been reached using observations.
                # Unknown-channel discovery is finished, clearance is not; the
                # remaining station obligations are cancelled. Re-using a station
                # as an optional localization point is left to the per-channel
                # certificate step, which can justify keeping specific sites.
                self.discovery_closed=True
                self.diagnostics['coverage_sites_cancelled']+=len(self.pending_stations)
                self.diagnostics['discovery_closed']+=1
                if discovered<16:self.diagnostics['discovery_closed_by_absence']+=1
                self.pending_stations=[]
            if self.discovery_closed and not self.deferred:
                break
            if self.reschedule_after_step and known and not self.pending_stations:
                # Coverage is finished and every known target stays mandatory;
                # resolve the nearest one directly instead of re-solving a
                # targets-only open route on every single measurement step.
                c=min(known,key=lambda ch:np.linalg.norm(self.region(ch)[1]-self.pos))
                self.locate(c)
                continue
            points=[self.region(c)[1] for c in known]+[self.stations[i] for i in self.pending_stations]
            nodes=[('target',c) for c in known]+[('station',i) for i in self.pending_stations]
            if not nodes:break
            self.diagnostics['route_replans']+=1
            kind,index=nodes[search_route(points,self.pos)[0]]
            if kind=='target':
                self.locate(index)
                continue
            self.pending_stations.remove(index);p=self.stations[index]
            if self.discovery_closed:
                # Discovery is over: only known targets are worth re-measuring;
                # an unresolved channel has no source and cannot answer.
                channels=[c for c in self.deferred if c not in self.cleared]
            else:
                channels=[c for c in range(1,21) if c not in self.cleared]
            if self.channel in channels:
                channels.remove(self.channel);channels.insert(0,self.channel)
            for c in channels:
                if self.skip_known_measurement(c,p):
                    self.diagnostics['skipped_known_measurements']+=1
                    continue
                if self.certify_channel_absence and self._station_channel_unneeded(index,c):
                    self.diagnostics['absence_skipped_measurements']+=1
                    continue
                result=self.action('/measure',p,c)['measure_result']
                if result=='near':
                    if not self.clear(p,c):raise RuntimeError('Near clear failed')
                elif result=='direction' and c not in self.deferred:
                    self.deferred[c]=len(self.visited)+1
                    self.diagnostics['deferred_targets']+=1
                elif result=='no_signal' and self.certify_channel_absence:
                    self._note_silent(c,index)
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
