"""Bounded observation steps (ported from teammate commit 66faa29, unmodified logic).

Provenance: upstream 66faa29 `成果/support/localization_service.py`; this copy keeps the
adaptive service (one measurement per scheduler visit, per-target attempt budget of 4,
Q4 current-position top-up) and the Q3 negative range exclusion `outside_disk_hull`.
Local wiring is opt-in only: `service_policy='adaptive'` on the Q4 solver; Q3 uses the
negative exclusion solely through the research variant that passed the inclusion proof.
"""
import numpy as np
from geometry import clip,feasible,enclosing_circle
from coverage_geometry import hull_normals
from solver import Solver


def outside_disk_hull(poly,q):
    """Outer convex relaxation of poly outside a guaranteed reception disk.

    Q3 no-signal from an uncleared source implies distance >1000m. Extreme
    points of the convex hull of the remainder are surviving polygon vertices
    or polygon-edge/circle intersections. Retain all components, using a
    smaller disk and outward half-plane slack for numerical safety.
    """
    radius=999.999
    rel=poly-q;d2=np.sum(rel*rel,axis=1)
    if np.all(d2>=radius*radius):return poly
    points=[p for p,dist in zip(poly,d2) if dist>=radius*radius]
    for a,b in zip(poly,np.roll(poly,-1,axis=0)):
        d=b-a;v=a-q;aa=float(d@d)
        if aa<1e-20:continue
        bb=2*float(v@d);cc=float(v@v)-radius*radius;disc=bb*bb-4*aa*cc
        if disc<0:continue
        for t in ((-bb-np.sqrt(disc))/(2*aa),(-bb+np.sqrt(disc))/(2*aa)):
            if 0<=t<=1:points.append(a+t*d)
    if not points:raise RuntimeError('Omni negative observation contradicts positive region')
    hb=hull_normals(points)
    if hb is None:return poly
    result=poly
    for n,b in zip(*hb):result=clip(result,n,float(b)+1e-5)
    if not len(result):raise RuntimeError('Empty omni region')
    return result


class LocalizationService:
    def __init__(self,controller):
        self.s=controller;self.attempts={};self.probed=set()
        self.negatives={c:[] for c in range(1,21)};self.cache={}

    def record(self,path,p,c,response):
        if self.s.problem==3 and path=='/measure' and response['measure_result']=='no_signal' and c not in self.s.cleared:
            self.negatives[c].append(np.array(p,copy=True))

    def omni_region(self,c):
        if self.s.problem!=3:raise ValueError('Negative range exclusion is Q3 only')
        key=(len(self.s.obs[c]),len(self.negatives[c]))
        if c not in self.cache or self.cache[c][0]!=key:
            poly=feasible(self.s.obs[c])
            for q in self.negatives[c]:poly=outside_disk_hull(poly,q)
            center,radius=enclosing_circle(poly)
            self.cache[c]=(key,poly,center,radius)
        return self.cache[c][1:]

    def advance_omni(self,c):
        s=self.s;poly,center,radius=s.region(c)
        if radius<=19.99:return s.certified_clear(c,poly,center,radius)
        if radius<=40 and (c,len(s.obs[c])) not in self.probed:
            self.probed.add((c,len(s.obs[c])));s.diagnostics['small_region_probes']+=1
            if s.clear(center,c):
                s.diagnostics['small_region_successes']+=1;return
        self.attempts[c]=self.attempts.get(c,0)+1
        if self.attempts[c]>4:return Solver.locate(s,c)
        s.diagnostics['service_steps']+=1
        q=s.next_measure(c,poly,center,radius)
        if q is None:return Solver.locate(s,c)
        result=s.action('/measure',q,c)['measure_result']
        if result=='near':
            if not s.clear(q,c):raise RuntimeError('Near clear failed')
        elif result=='no_signal':return Solver.locate(s,c)

    def advance_directional(self,c):
        s=self.s
        s.diagnostics['service_steps']+=1
        self.attempts[c]=self.attempts.get(c,0)+1
        poly,center,radius=s.region(c)
        # After four partial attempts, complete this source with the existing
        # locator and optical fallback. No unresolved source is discarded.
        if radius<=40 or self.attempts[c]>4:return s.locate(c)
        if self.attempts[c]>1:s.diagnostics['service_resumes']+=1
        if np.linalg.norm(s.pos-s.obs[c][-1][0])>80 and not any(np.linalg.norm(s.pos-p)<.1 for p in s.measured[c]):
            result=s.action('/measure',s.pos,c)['measure_result']
            if result=='near':
                if not s.clear(s.pos,c):raise RuntimeError('Near clear failed')
                return
            if result=='direction':return
            poly,center,radius=s.region(c)
            if radius<=19.99:return s.certified_clear(c,poly,center,radius)
        p0=s.obs[c][-1][0];d=center-p0;length=np.linalg.norm(d)
        if length<1e-8:return s.locate(c)
        side=np.array([-d[1],d[0]])/length
        options=[p0+.8*d+sign*min(100.,.35*length)*side for sign in (-1,1)]
        options.sort(key=lambda p:np.linalg.norm(p-s.pos))
        q=Solver.next_measure(s,c,poly,center,radius)
        if q is not None:options.insert(0,q)
        for q in options:
            if any(np.linalg.norm(q-p)<.1 for p in s.measured[c]):continue
            result=s.action('/measure',q,c)['measure_result']
            if result=='near':
                if not s.clear(q,c):raise RuntimeError('Near clear failed')
                return
            if result=='direction':return
        return s.locate(c)
