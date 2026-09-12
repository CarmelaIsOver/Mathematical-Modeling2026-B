"""Single observation-only controller for both problems.

Coverage and geometric certificates provide completeness; routing is heuristic.
"""
import time, math
import numpy as np
from geometry import feasible,enclosing_circle,optical_cover,search_stations,bearing_clip,EPS_DEG


def safe_clear_point(current,center,radius):
    """Projection onto a sufficient safe disk; radius error margin retained."""
    if radius>19.99:
        raise ValueError('Region cannot be certified by a 19.99m disk')
    d=np.asarray(current)-center
    distance=np.linalg.norm(d)
    slack=max(0.,19.99-radius)
    return np.asarray(current).copy() if distance<=slack else center+d*(slack/max(distance,1e-15))

def open_route(points,start,end=None):
    """Nearest-neighbor seed and bounded 2-opt; optimize estimated open path."""
    if not len(points):return []
    points=np.asarray(points)
    pending=list(range(len(points)));order=[];p=np.asarray(start)
    while pending:
        j=min(pending,key=lambda i:np.linalg.norm(points[i]-p))
        order.append(j);pending.remove(j);p=points[j]
    def edge(a,b):return float(np.linalg.norm(a-b))
    # At most three improving passes, independent of the simulator speed.
    for _ in range(3):
        improved=False
        for i in range(len(order)-1):
            before=start if i==0 else points[order[i-1]]
            for j in range(i+1,len(order)):
                after=points[order[j+1]] if j+1<len(order) else end
                old=edge(before,points[order[i]])
                new=edge(before,points[order[j]])
                if after is not None:
                    old+=edge(points[order[j]],after)
                    new+=edge(points[order[i]],after)
                if new+1e-7<old:
                    order[i:j+1]=reversed(order[i:j+1]);improved=True
        if not improved:break
    return order

class Solver:
    def __init__(self,backend,problem,spacing=950.,max_refine=8,coverage_layout='original'):
        self.api=backend;self.problem=problem;self.max_refine=max_refine
        self.stations=search_stations(problem,spacing,layout=coverage_layout)
        self.pos=np.zeros(2);self.channel=1;self.cleared=set()
        self.obs={c:[] for c in range(1,21)}
        self.counts={'measure':0,'clear':0,'failed_clear':0,'fallback':0}
        self.visited=[];self.deadline=float('inf')
        self.cache={};self.measured={c:[] for c in range(1,21)}
        self.pending_stations=[];self.deferred={};self.max_defer_stations=3
        self.parts={'move_s':0.,'switch_s':0.,'measure_s':0.,'optical_s':0.,'laser_s':0.}
        self.diagnostics={'candidate_evaluations':0,'deferred_targets':0,'forced_targets':0,
                          'opportunistic_measures':0,'safe_clear_points':0}
        self.certificates=[]

    def action(self,path,p,c):
        if time.monotonic()>self.deadline-3:raise TimeoutError('Insufficient remaining real duration')
        old_pos=self.pos.copy();old_channel=self.channel
        r=self.api.action(path,p,c)
        self.pos=np.asarray(p,dtype=float)
        self.parts['move_s']+=float(np.linalg.norm(self.pos-old_pos))/5
        if path=='/measure':
            self.channel=c;self.counts['measure']+=1
            if r['measure_result']=='direction':self.obs[c].append((self.pos.copy(),float(r['svd_deg'])))
            self.parts['measure_s']+=5;self.parts['switch_s']+=int(c!=old_channel)
            self.measured[c].append(self.pos.copy())
        else:
            self.counts['clear']+=1;self.parts['optical_s']+=3
            if r['clear_result']=='success':self.cleared.add(c);self.parts['laser_s']+=2
            else:self.counts['failed_clear']+=1
        return r

    def clear(self,p,c):
        return self.action('/clear',p,c)['clear_result']=='success'

    def certified_clear(self,c,poly,center,radius):
        p=safe_clear_point(self.pos,center,radius)
        bound=float(np.max(np.linalg.norm(poly-p,axis=1)))
        if bound>19.990001:raise RuntimeError('Unsafe clear candidate')
        self.certificates.append({'channel':c,'vertex_bound_m':bound})
        self.diagnostics['safe_clear_points']+=1
        if not self.clear(p,c):raise RuntimeError('Certified clear failed')

    def next_station(self):
        pending=self.pending_stations
        if self.problem==4:
            inner=[i for i in pending if np.linalg.norm(self.stations[i])<=1800]
            pending=inner or pending
        return pending[open_route(self.stations[pending],self.pos)[0]]

    def process_found(self,found):
        while found:
            centers=np.array([self.region(c)[1] for c in found])
            end=self.stations[self.next_station()] if self.pending_stations else None
            c=found.pop(open_route(centers,self.pos,end=end)[0])
            self.locate(c)


    def region(self, c):
        n = len(self.obs[c])
        if c not in self.cache or self.cache[c][0] != n:
            poly = feasible(self.obs[c])
            if len(poly) == 0:
                raise ValueError('Empty feasible region')
            center, radius = enclosing_circle(poly)
            self.cache[c] = (n, poly, center, radius)
        return self.cache[c][1:]

    def next_measure(self, c, poly, center, radius):
        current = self.pos.copy()
        p0 = self.obs[c][-1][0]
        candidates = [current]
        for origin in (current, p0):
            d = center - origin
            length = np.linalg.norm(d)
            if length < 1e-08:
                continue
            u = d / length
            v = np.array([-u[1], u[0]])
            for fraction in (0.5, 0.8, 1.0):
                for offset in (0.0, -1.0, 1.0):
                    lateral = min(100.0, max(25.0, 0.25 * length))
                    candidates.append(origin + fraction * d + offset * lateral * v)
            for sign in (-1, 1):
                candidates.append(origin + 0.65 * d + sign * min(100.0, 0.35 * length) * v)
        if len(self.obs[c]) > 1:
            candidates.append((self.obs[c][0][0] + p0) / 2)
        samples = np.vstack([poly * 0.8 + center * 0.2, center[None, :]])
        if len(samples) > 9:
            samples = samples[np.linspace(0, len(samples) - 1, 9, dtype=int)]
        previous = np.array([p for p, a in self.obs[c]])
        normals = np.array([[math.cos(a), math.sin(a)] for a in np.linspace(0, 2 * math.pi, 48, endpoint=False)])
        admissible = []
        for g in samples:
            mask = np.all((previous - g) @ normals.T >= -1e-07, axis=0)
            admissible.append(mask)
        best = None
        best_score = float('inf')
        seen = set()
        for q in candidates:
            key = tuple(np.round(q, 3))
            if key in seen:
                continue
            seen.add(key)
            if any((np.linalg.norm(q - p) < 0.1 for p in self.measured[c])):
                continue
            move = float(np.linalg.norm(q - current)) / 5
            radii = []
            visible = []
            for g, mask in zip(samples, admissible):
                delta = g - q
                beta = math.degrees(math.atan2(delta[1], delta[0])) % 360
                post = bearing_clip(poly, q, beta, 2 * EPS_DEG)
                if len(post):
                    m = post.mean(axis=0)
                    radii.append(float(np.max(np.linalg.norm(post - m, axis=1))))
                else:
                    radii.append(radius)
                lower = max(1000.0, float(np.max(np.linalg.norm(previous - g, axis=1))))
                distance = float(np.linalg.norm(q - g))
                distance_weight = 1.0 if distance <= lower else max(0.0, (1500.0 - distance) / max(1.0, 1500.0 - lower))
                if self.problem == 4 and np.any(mask):
                    orientation = float(np.mean((q - g) @ normals[mask].T >= 0))
                else:
                    orientation = 1.0
                visible.append(distance_weight * orientation)
            rpred = float(np.mean(radii))
            prob = float(np.mean(visible))
            remaining = float(np.mean(np.linalg.norm(samples - q, axis=1))) / 5
            score = move + 5 + int(c != self.channel) + remaining + 0.4 * rpred + 15 * (rpred > 20)
            score += (1 - prob) * (45 + move + 0.2 * radius)
            self.diagnostics['candidate_evaluations'] += 1
            if score < best_score:
                best_score = score
                best = q
        return best

    def locate(self, c):
        if self.problem == 4:
            return self.locate_directional(c)
        dark = 0
        for _ in range(self.max_refine):
            poly, center, radius = self.region(c)
            if radius <= 19.99:
                self.certified_clear(c, poly, center, radius)
                return
            q = self.next_measure(c, poly, center, radius)
            if q is None:
                break
            r = self.action('/measure', q, c)
            if r['measure_result'] == 'near':
                if not self.clear(self.pos, c):
                    raise RuntimeError('Near clear failed')
                return
            if r['measure_result'] == 'no_signal':
                dark += 1
                if dark >= 2:
                    break
            else:
                dark = 0
        poly, center, radius = self.region(c)
        if radius <= 19.99:
            self.certified_clear(c, poly, center, radius)
            return
        self.counts['fallback'] += 1
        points = optical_cover(poly, self.obs[c][0][1])
        points = points[open_route(points, self.pos)]
        for p in points:
            if self.clear(p, c):
                return
        raise RuntimeError('Exhausted optical cover')

    def locate_directional(self, c):
        if np.linalg.norm(self.pos - self.obs[c][-1][0]) > 80 and (not any((np.linalg.norm(self.pos - p) < 0.1 for p in self.measured[c]))):
            r = self.action('/measure', self.pos, c)
            if r['measure_result'] == 'near':
                if not self.clear(self.pos, c):
                    raise RuntimeError('Near clear failed')
                return
        for _ in range(self.max_refine):
            poly, center, radius = self.region(c)
            if radius <= 19.99:
                self.certified_clear(c, poly, center, radius)
                return
            p0 = self.obs[c][-1][0]
            d = center - p0
            length = np.linalg.norm(d)
            if length < 1e-08:
                break
            v = np.array([-d[1], d[0]]) / length
            options = [p0 + 0.8 * d + sign * min(100.0, 0.35 * length) * v for sign in (-1, 1)]
            options.sort(key=lambda p: np.linalg.norm(p - self.pos))
            positive = False
            for q in options:
                r = self.action('/measure', q, c)
                if r['measure_result'] == 'near':
                    if not self.clear(self.pos, c):
                        raise RuntimeError('Near clear failed')
                    return
                if r['measure_result'] == 'direction':
                    positive = True
                    break
            if not positive:
                break
        poly, center, radius = self.region(c)
        if radius <= 19.99:
            self.certified_clear(c, poly, center, radius)
            return
        self.counts['fallback'] += 1
        points = optical_cover(poly, self.obs[c][0][1])
        points = points[open_route(points, self.pos)]
        for p in points:
            if self.clear(p, c):
                return
        raise RuntimeError('Exhausted optical cover')

    def run(self):
        start = time.perf_counter()
        entered = self.api.enter()
        self.deadline = time.monotonic() + entered['remaining_real_duration_s']
        self.pending_stations = list(range(len(self.stations)))
        joint = self.problem == 3
        while self.pending_stations or self.deferred:
            self.deferred = {c: age for c, age in self.deferred.items() if c not in self.cleared}
            if len(self.cleared) == 16:
                break
            if joint and self.deferred:
                keys = list(self.deferred)
                overdue = [c for c in keys if len(self.visited) - self.deferred[c] >= self.max_defer_stations]
                if overdue or not self.pending_stations:
                    forced = overdue or keys
                    c = min(forced, key=lambda c: np.linalg.norm(self.region(c)[1] - self.pos))
                    self.diagnostics['forced_targets'] += 1
                    self.locate(c)
                    self.deferred.pop(c, None)
                    continue
                nodes = [('target', c) for c in keys] + [('station', j) for j in self.pending_stations]
                points = np.array([self.region(c)[1] for c in keys] + [self.stations[j] for j in self.pending_stations])
                kind, which = nodes[open_route(points, self.pos)[0]]
                if kind == 'target':
                    self.locate(which)
                    self.deferred.pop(which, None)
                    continue
                i = which
            elif self.pending_stations:
                i = self.next_station()
            else:
                break
            self.pending_stations.remove(i)
            p = self.stations[i]
            found = []
            channels = [c for c in range(1, 21) if c not in self.cleared]
            if self.channel in channels:
                channels.remove(self.channel)
                channels.insert(0, self.channel)
            for c in channels:
                r = self.action('/measure', p, c)
                if r['measure_result'] == 'near':
                    if not self.clear(p, c):
                        raise RuntimeError('Near clear failed')
                elif r['measure_result'] == 'direction':
                    found.append(c)
                if c in self.deferred:
                    self.diagnostics['opportunistic_measures'] += 1
            self.visited.append(i)
            if joint:
                for c in found:
                    if c not in self.deferred:
                        self.deferred[c] = len(self.visited)
                        self.diagnostics['deferred_targets'] += 1
            else:
                self.process_found(found)
            if len(self.cleared) == 16:
                break
        if len(self.cleared) < 16 and (self.pending_stations or any((c not in self.cleared for c in self.deferred))):
            raise RuntimeError('Cannot finish with unresolved coverage or targets')
        exited = self.api.exit()
        if exited.get('accepted') is not True or exited.get('exit_reason') != 'user_exit':
            raise RuntimeError('Normal exit not acknowledged')
        total = self.api.virtual_time
        return dict(problem=self.problem, cleared=len(self.cleared), virtual_time_s=total, mean_time_s=total / len(self.cleared) if self.cleared else None, program_time_s=time.perf_counter() - start, complete=True, stations_visited=len(self.visited), **self.counts, **self.parts, **self.diagnostics)
