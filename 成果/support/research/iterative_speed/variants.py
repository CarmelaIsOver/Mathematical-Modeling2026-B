"""Experimental policies on commit 951df1b. No simulator state is inspected."""
import math
import itertools
import numpy as np
from omni_search import OmniSearchSolver
from joint_search import JointSearchSolver,search_route
from geometry import search_stations


class OmniVariant(OmniSearchSolver):
    def __init__(self, *args, ring_radius=None, ring_count=6, probe_radius=0., guard_initial=False,
                 close_known=False, guard_visits=0, skip_known_radius=None,
                 align_ring=False, two_stage_radius=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.probe_radius=probe_radius
        self.skip_known_radius=skip_known_radius
        self.ring_points=None;self.guard_initial=guard_initial;self.close_known=close_known
        self.guard_visits=guard_visits
        self.observed_channels=set();self.ring_activated=False
        self.ring_radius=ring_radius;self.ring_count=ring_count
        self.align_ring=align_ring;self.two_stage_radius=two_stage_radius
        self.first_bearing=None;self.positive_count=0
        if ring_radius is not None:
            self._validate_radius(ring_radius,ring_count)
            angles=np.arange(ring_count)*2*math.pi/ring_count
            self.ring_points=np.vstack([np.zeros((1,2)),ring_radius*np.c_[np.cos(angles),np.sin(angles)]])
            if not guard_initial:self.stations=self.ring_points.copy();self.ring_activated=True
        if two_stage_radius is not None:
            self._validate_radius(two_stage_radius,ring_count)
        self.diagnostics['extra_probe_attempts']=0
        self.diagnostics['extra_probe_successes']=0
        self.diagnostics['ring_activated']=0

    @staticmethod
    def _validate_radius(radius,ring_count):
        c=math.cos(math.pi/ring_count)
        disc=max(0.,(1800*c)**2-(1800**2-1000**2))
        lo=1800*c-math.sqrt(disc);hi=min(2000*c,1800*c+math.sqrt(disc))
        if not lo+1e-4<=radius<=hi-1e-4:
            raise ValueError('Outside complete ring covering interval')

    def _install_ring(self,radius):
        angles=np.arange(self.ring_count)*2*math.pi/self.ring_count
        if self.align_ring and self.first_bearing is not None:
            angles=angles+math.radians(self.first_bearing)
        self.stations=np.vstack([np.zeros((1,2)),radius*np.c_[np.cos(angles),np.sin(angles)]])
        # Rebuild pending indices: a layout with a different station count must
        # keep every unvisited site, preserving visited indices.
        self.pending_stations=[i for i in range(len(self.stations)) if i not in self.visited]
        self.ring_activated=True
        self.diagnostics['ring_activated']=1
        self.diagnostics['ring_radius_used']=radius

    def action(self,path,p,c):
        r=super().action(path,p,c)
        if path=='/measure' and r['measure_result'] in ('direction','near'):
            self.observed_channels.add(c)
            if self.guard_initial and len(self.visited)<=self.guard_visits:
                self.positive_count+=1
                if r['measure_result']=='direction' and self.first_bearing is None:
                    self.first_bearing=float(r.get('svd_deg',0.))
                if not self.ring_activated:
                    self._install_ring(self.two_stage_radius if self.two_stage_radius is not None
                                       else self.ring_radius)
                elif (self.two_stage_radius is not None and self.positive_count>=2
                      and self.diagnostics.get('ring_radius_used')==self.two_stage_radius):
                    self._install_ring(self.ring_radius)
            if self.close_known and len(self.observed_channels)==16:
                self.diagnostics['coverage_cancelled']=self.diagnostics.get('coverage_cancelled',0)+len(self.pending_stations)
                self.pending_stations=[]
        return r

    def skip_station_measurement(self,c,p):
        if self.skip_known_radius is not None and c in self.deferred:
            # Known targets are cleared regardless; a station pass beyond this
            # distance adds a scan without a reliable movement benefit.
            _,center,radius=self.region(c)
            if np.linalg.norm(np.asarray(center)-np.asarray(p))>self.skip_known_radius:
                return True
        return super().skip_station_measurement(c,p)

    def locate(self,c):
        _,center,radius=self.region(c)
        if 19.99<radius<=self.probe_radius:
            self.diagnostics['extra_probe_attempts']+=1
            if self.clear(center,c):
                self.diagnostics['extra_probe_successes']+=1
                return
        return super().locate(c)


class DirectionalVariant(JointSearchSolver):
    def __init__(self,*args,alpha=.8,lateral_cap=100.,**kwargs):
        super().__init__(*args,**kwargs)
        self.alpha=alpha;self.lateral_cap=lateral_cap

    def directional_options(self,c,poly,center,radius):
        p0=self.obs[c][-1][0];d=center-p0;length=np.linalg.norm(d)
        if length<1e-8:return []
        side=np.array([-d[1],d[0]])/length
        options=[p0+self.alpha*d+sign*min(self.lateral_cap,.35*length)*side for sign in (-1,1)]
        options.sort(key=lambda p:np.linalg.norm(p-self.pos))
        if radius<=120:
            q=self.next_measure(c,poly,center,radius)
            if q is not None:options.insert(0,q)
        return options


class FinishStep(JointSearchSolver):
    """Keep discovery behavior unchanged; only interrupt service after discovery."""
    def locate(self,c):
        self.reschedule_after_step=self.discovery_closed or not self.pending_stations
        return super().locate(c)


class ConvexCandidates(JointSearchSolver):
    """Positive reception positions have a convex shared reception region."""
    def candidates(self,c,poly,center,radius):
        result=super().candidates(c,poly,center,radius)
        positions=[p for p,a in self.obs[c][-3:]]
        for a,b in itertools.combinations(positions,2):
            delta=b-a;length2=delta@delta
            if length2<1e-8:continue
            fractions=[.25,.5,.75,float(np.clip((self.pos-a)@delta/length2,0,1))]
            for f in fractions:
                q=a+f*delta
                if any(np.linalg.norm(q-p)<.1 for p in self.measured[c]+result):continue
                result.append(q)
        return result


class DuringProbe(JointSearchSolver):
    """A bounded optical trial may replace the final extra bearing, not its certificate."""
    def _locate_full(self,c):
        if self._small_region_probe(c):return
        return self.locate_directional(c)

    def locate_directional(self,c):
        if np.linalg.norm(self.pos-self.obs[c][-1][0])>80 and not any(np.linalg.norm(self.pos-p)<.1 for p in self.measured[c]):
            result=self.action('/measure',self.pos,c)['measure_result']
            if result=='near':
                if not self.clear(self.pos,c):raise RuntimeError('Near clear failed')
                return
        for _ in range(self.max_refine):
            poly,center,radius=self.region(c)
            if radius<=19.99:
                self.certified_clear(c,poly,center,radius);return
            if radius<=30. and self._small_region_probe(c):return
            options=self.directional_options(c,poly,center,radius)
            positive=False
            for q in options:
                if any(np.linalg.norm(q-p)<.1 for p in self.measured[c]):continue
                result=self.action('/measure',q,c)['measure_result']
                if result=='near':
                    if not self.clear(q,c):raise RuntimeError('Near clear failed')
                    return
                if result=='direction':positive=True;break
            if not positive:break
        return self.directional_fallback(c)


class ChooseLayout(JointSearchSolver):
    """Choose one complete layout after the common center scan, before moving."""
    def __init__(self,*args,switch_threshold=.98,**kwargs):
        super().__init__(*args,**kwargs)
        if self.certify_channel_absence:raise ValueError('This experiment uses no cell-indexed state')
        self.switch_threshold=switch_threshold
        self.layout_selected=False
        self.origin_index=int(np.argmin(np.linalg.norm(self.stations,axis=1)))
        self.diagnostics['selected_22']=0

    def action(self,path,p,c):
        r=super().action(path,p,c)
        if not self.layout_selected and path=='/measure' and c==20 and not self.visited and np.linalg.norm(self.pos)<1e-7:
            self.layout_selected=True
            known=[k for k in self.obs if self.obs[k] and k not in self.cleared]
            # No central discovery: retain the reference's outer-search behavior.
            if not known:return r
            rings=search_stations(4,950.,layout='rings')
            candidates=[self.stations,rings];costs=[]
            for points in candidates:
                remaining=[p for p in points if np.linalg.norm(p)>1e-7]
                nodes=np.array([self.region(k)[1] for k in known]+remaining)
                route=search_route(nodes,self.pos)
                chain=np.vstack([self.pos,nodes[route]])
                cost=float(np.linalg.norm(np.diff(chain,axis=0),axis=1).sum())/5
                for q in remaining:
                    for k in self.obs:
                        if k in self.cleared:continue
                        if k in known:
                            _,center,radius=self.region(k)
                            if radius<=19.99 or np.linalg.norm(q-center)-radius>1500 or (len(self.obs[k])>=2 and radius<=40):continue
                        cost+=6.
                costs.append(cost)
            self.diagnostics['layout_cost25']=costs[0];self.diagnostics['layout_cost22']=costs[1]
            if costs[1]<self.switch_threshold*costs[0]:
                # Preserve the index of the already visited origin. The current
                # station scan keeps its local p; all pending indices are rebuilt.
                others=[q for q in rings if np.linalg.norm(q)>1e-7]
                others.insert(self.origin_index,np.zeros(2));self.stations=np.array(others)
                self.pending_stations=[i for i in range(len(self.stations)) if i!=self.origin_index]
                self.diagnostics['selected_22']=1
        return r


VARIANTS={
 3:{'baseline':(OmniSearchSolver,{}), 'negative':(OmniSearchSolver,{'negative_observations':True}),
    'ring1300':(OmniVariant,{'ring_radius':1300.}), 'ring1123':(OmniVariant,{'ring_radius':1123.}),
    'probe30':(OmniVariant,{'probe_radius':30.}), 'probe40':(OmniVariant,{'probe_radius':40.}),
    'ring1123_negative':(OmniVariant,{'ring_radius':1123.,'negative_observations':True}),
    'ring1300_negative':(OmniVariant,{'ring_radius':1300.,'negative_observations':True}),
    'guard1123':(OmniVariant,{'ring_radius':1123.,'guard_initial':True}),
    'guard1300':(OmniVariant,{'ring_radius':1300.,'guard_initial':True}),
    'guard1180':(OmniVariant,{'ring_radius':1180.,'guard_initial':True}),
    'guard1250':(OmniVariant,{'ring_radius':1250.,'guard_initial':True}),
    'guard1400':(OmniVariant,{'ring_radius':1400.,'guard_initial':True}),
    'guard1123_neg':(OmniVariant,{'ring_radius':1123.,'guard_initial':True,'negative_observations':True}),
    'guard1123_close':(OmniVariant,{'ring_radius':1123.,'guard_initial':True,'close_known':True}),
    'guard1123_close_skip14':(OmniVariant,{'ring_radius':1123.,'guard_initial':True,'close_known':True,'skip_known_radius':1400.}),
    'guard1123_close_skip12':(OmniVariant,{'ring_radius':1123.,'guard_initial':True,'close_known':True,'skip_known_radius':1200.}),
    'guard1150_close_skip12':(OmniVariant,{'ring_radius':1150.,'guard_initial':True,'close_known':True,'skip_known_radius':1200.}),
    'guard1180_close_skip12':(OmniVariant,{'ring_radius':1180.,'guard_initial':True,'close_known':True,'skip_known_radius':1200.}),
    'guard1123_close_skip12_align':(OmniVariant,{'ring_radius':1123.,'guard_initial':True,'close_known':True,'skip_known_radius':1200.,'align_ring':True}),
    'guard1123_close_skip12_2stage':(OmniVariant,{'ring_radius':1123.,'guard_initial':True,'close_known':True,'skip_known_radius':1200.,'two_stage_radius':1300.}),
    'guard1123_close_skip12_2stage_align':(OmniVariant,{'ring_radius':1123.,'guard_initial':True,'close_known':True,'skip_known_radius':1200.,'two_stage_radius':1300.,'align_ring':True}),
    'guard1123_close_skip10':(OmniVariant,{'ring_radius':1123.,'guard_initial':True,'close_known':True,'skip_known_radius':1000.}),
    'guard1123_close_skip8':(OmniVariant,{'ring_radius':1123.,'guard_initial':True,'close_known':True,'skip_known_radius':800.}),
    'guard1140_close':(OmniVariant,{'ring_radius':1140.,'guard_initial':True,'close_known':True}),
    'guard1160_close':(OmniVariant,{'ring_radius':1160.,'guard_initial':True,'close_known':True}),
    'guard1200_close':(OmniVariant,{'ring_radius':1200.,'guard_initial':True,'close_known':True}),
    'guard1123_neg_close':(OmniVariant,{'ring_radius':1123.,'guard_initial':True,'close_known':True,'negative_observations':True}),
    'guard1123_late':(OmniVariant,{'ring_radius':1123.,'guard_initial':True,'guard_visits':1}),
    'guard_ring7':(OmniVariant,{'ring_radius':997.5,'ring_count':7,'guard_initial':True}),
    'guard_ring7_close':(OmniVariant,{'ring_radius':997.5,'ring_count':7,'guard_initial':True,'close_known':True}),
    'guard_ring8':(OmniVariant,{'ring_radius':938.1,'ring_count':8,'guard_initial':True}),
    'guard_ring8_close':(OmniVariant,{'ring_radius':938.1,'ring_count':8,'guard_initial':True,'close_known':True}),
    'guard_ring9':(OmniVariant,{'ring_radius':903.5,'ring_count':9,'guard_initial':True}),
    'guard_ring9_close':(OmniVariant,{'ring_radius':903.5,'ring_count':9,'guard_initial':True,'close_known':True}),
    'ring1123_close_unguarded':(OmniVariant,{'ring_radius':1123.,'close_known':True}),
    'closure':(OmniVariant,{'close_known':True})},
 4:{'baseline':(JointSearchSolver,{}), 'rings22':(JointSearchSolver,{'coverage_layout':'rings'}),
    'step55':(DirectionalVariant,{'alpha':.55,'lateral_cap':40.}),
    'step65':(DirectionalVariant,{'alpha':.65,'lateral_cap':60.}),
    'step80narrow':(DirectionalVariant,{'alpha':.8,'lateral_cap':40.}),
    'rings55':(DirectionalVariant,{'coverage_layout':'rings','alpha':.55,'lateral_cap':40.}),
    'finish_step':(FinishStep,{}), 'convex_candidates':(ConvexCandidates,{}),
    'during_probe':(DuringProbe,{}), 'choose_layout':(ChooseLayout,{}),
    'choose_strict85':(ChooseLayout,{'switch_threshold':.85}),
    'choose_strict92':(ChooseLayout,{'switch_threshold':.92}),
    'choose_aggressive':(ChooseLayout,{'switch_threshold':1.05})}
}
