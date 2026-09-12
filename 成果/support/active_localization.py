"""Opt-in paper-inspired localization for the shared offline/HTTP entry.

Uses bounded geometry rather than the papers' Gaussian/EKF estimator.
Independent benchmarks did not meet the adoption threshold; enable explicitly
for practice using --strategy paper. No simulator truth is accessible here.
"""
import math
import numpy as np
from solver import Solver, open_route
from geometry import bearing_clip, diameter, EPS_DEG, optical_cover


def radius_bound(poly):
    """A containing circle, not an optimistic diameter/2 approximation."""
    if not len(poly):
        return 0., np.zeros(2)
    _, (a,b) = diameter(poly)
    center=(a+b)/2
    return float(np.max(np.linalg.norm(poly-center,axis=1))), center


def outcomes(poly, q, bins=24):
    """Cover ALL possible positive bearing outputs by overlapping outer wedges.

    Each bin expands its wedge by half its angular width. Thus every exact
    posterior in that bin is contained in the computed polygon. The radius
    bounds concern positive outputs only, never the no-signal branch.
    """
    delta=poly-q
    edges=np.roll(poly,-1,axis=0)-poly
    rel=q-poly
    crosses=edges[:,0]*rel[:,1]-edges[:,1]*rel[:,0]
    if np.all(crosses>=-1e-8) or np.all(crosses<=1e-8):
        return [(poly,1.)]
    middle=math.atan2(*(poly.mean(axis=0)-q)[::-1])
    angles=np.angle(np.exp(1j*(np.arctan2(delta[:,1],delta[:,0])-middle)))
    lo=float(angles.min())-math.radians(EPS_DEG)
    hi=float(angles.max())+math.radians(EPS_DEG)
    step=(hi-lo)/bins
    result=[]
    for i in range(bins):
        angle=middle+lo+(i+.5)*step
        post=bearing_clip(poly,q,math.degrees(angle),EPS_DEG+math.degrees(step)/2)
        if len(post):result.append((post,step))
    return result


class ActiveLocalizationSolver(Solver):

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.diagnostics['paper_measurements_selected']=0

    def candidates(self,c,poly,center,radius):
        _,(a,b)=diameter(poly)
        u=(b-a)/max(1e-12,np.linalg.norm(b-a))
        v=np.array([-u[1],u[0]])
        # The bounded region supplies shape; no fabricated covariance or prior.
        halfwidth=float(np.max(np.abs((poly-center)@v)))
        candidates=[self.pos.copy()]
        for fraction in (.25,.5,.75,.9,1.):
            candidates.append(self.pos+fraction*(center-self.pos))
        for scale in (.15,.3,.6,1.):
            offset=max(halfwidth+5.,radius*scale,15.)
            candidates.extend([center+offset*v,center-offset*v])
        p0=self.obs[c][-1][0]
        d=center-p0;length=np.linalg.norm(d)
        if length>1e-8:
            side=np.array([-d[1],d[0]])/length
            # Include the working controller's local fallback geometry.
            for fraction in (.5,.8):
                for sign in (-1,1):
                    candidates.append(p0+fraction*d+sign*min(100.,.35*length)*side)
        unique=[]
        for q in candidates:
            if any(np.linalg.norm(q-p)<.1 for p in self.measured[c]):continue
            if any(np.linalg.norm(q-p)<.1 for p in unique):continue
            unique.append(q)
        return unique

    def visibility(self,c,poly,q):
        """Heuristic ranking only. No deletion of feasible target positions."""
        probes=np.vstack([poly,poly.mean(axis=0)])
        previous=np.array([p for p,a in self.obs[c]])
        normals=np.array([[math.cos(a),math.sin(a)] for a in np.linspace(0,2*math.pi,72,endpoint=False)])
        values=[]
        for g in probes:
            lower=max(1000.,float(np.max(np.linalg.norm(previous-g,axis=1))))
            distance=np.linalg.norm(q-g)
            reception=1. if distance<=lower else max(0.,(1500.-distance)/max(1.,1500.-lower))
            if self.problem==4:
                mask=np.all((previous-g)@normals.T>=-1e-7,axis=0)
                if np.any(mask):reception*=float(np.mean((q-g)@normals[mask].T>=-1e-7))
            values.append(reception)
        return float(np.mean(values))

    def next_measure(self,c,poly,center,radius):
        if radius>120:
            return super().next_measure(c,poly,center,radius)
        # Only use the new geometry for a certified last positive measurement.
        # Unresolved candidates retain the established refinement policy.
        choices=[]
        for q in self.candidates(c,poly,center,radius):
            if self.visibility(c,poly,q)<.995:continue
            branches=outcomes(poly,q,bins=48)
            if not branches:continue
            costs=[]
            for post,w in branches:
                r,m=radius_bound(post)
                if r>19.99:break
                costs.append(max(0.,np.linalg.norm(q-m)-(19.99-r))/5)
            else:
                score=np.linalg.norm(q-self.pos)/5+5+int(c!=self.channel)+max(costs)
                choices.append((score,q))
            self.diagnostics['candidate_evaluations']+=1
        if choices:
            self.diagnostics['paper_measurements_selected']+=1
            return min(choices,key=lambda x:x[0])[1]
        return super().next_measure(c,poly,center,radius)

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
            p0=self.obs[c][-1][0];d=center-p0;length=np.linalg.norm(d)
            if length<1e-8:break
            side=np.array([-d[1],d[0]])/length
            options=[p0+.8*d+sign*min(100.,.35*length)*side for sign in (-1,1)]
            options.sort(key=lambda p:np.linalg.norm(p-self.pos))
            if radius<=120:
                q=self.next_measure(c,poly,center,radius)
                if q is not None:options.insert(0,q)
            positive=False
            for q in options:
                if any(np.linalg.norm(q-p)<.1 for p in self.measured[c]):continue
                result=self.action('/measure',q,c)['measure_result']
                if result=='near':
                    if not self.clear(q,c):raise RuntimeError('Near clear failed')
                    return
                if result=='direction':positive=True;break
            if not positive:break
        poly,center,radius=self.region(c)
        if radius<=19.99:
            self.certified_clear(c,poly,center,radius);return
        self.counts['fallback']+=1
        points=optical_cover(poly,self.obs[c][0][1])
        for i in open_route(points,self.pos):
            if self.clear(points[i],c):return
        raise RuntimeError('Exhausted optical cover')
