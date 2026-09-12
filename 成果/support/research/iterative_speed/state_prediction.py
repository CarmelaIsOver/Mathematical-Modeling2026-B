"""Direction C: joint positive/negative observation state prediction for Q4.

Bounded scope (per PI_NEXT_GOAL): keep the 25-site coverage, the certified enclosure
and every fallback point. Only the *order* of the fallback points and of the local
directional options is changed, ranked by how much hypothesis-sample mass they can
finish, where the samples are filtered by the real negative observations.

State layer: hypothesis samples (g, R, theta) with g uniform in the current positive
posterior polygon, R in {1000, 1250, 1500} and theta in 24 directions. A sample is kept
only if some (R, theta) explains every recorded no_signal at p:

    no_signal(p)  <=>  |g-p| > R   OR   (p-g)·v(theta) < 0

(the disjunction is the Q4 visibility rule; Q4 no_signal is never turned into a
position half-plane). Samples are planning candidates, never a certificate: they can
re-rank actions only, and no particle set is allowed to certify or to declare a
channel absent.
"""
import math

import numpy as np

from joint_search import JointSearchSolver


def _inside_convex(poly, q, eps=1e-9):
    """True when q is inside a consistently oriented convex polygon."""
    n = len(poly)
    if n < 3:
        return False
    pos = neg = False
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        cross = (b[0] - a[0]) * (q[1] - a[1]) - (b[1] - a[1]) * (q[0] - a[0])
        if cross > eps:
            pos = True
        elif cross < -eps:
            neg = True
        if pos and neg:
            return False
    return True


class JointStatePrediction(JointSearchSolver):
    def __init__(self, *args, n_samples=64, use_prediction=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.n_samples = int(n_samples)
        self.use_prediction = bool(use_prediction)
        self.negatives = {}
        self.diagnostics.update(pred_negatives=0, pred_calls=0, pred_samples_kept=0,
                                pred_samples_total=0, pred_reorders=0)

    # ---- state layer ---------------------------------------------------
    def action(self, path, p, c):
        r = super().action(path, p, c)
        if path == '/measure' and r['measure_result'] == 'no_signal':
            self.negatives.setdefault(c, []).append(np.asarray(p, float))
            self.diagnostics['pred_negatives'] += 1
        return r

    def _hypothesis_samples(self, c):
        poly, center, radius = self.region(c)
        if radius <= 1e-9 or len(poly) < 3:
            return np.zeros((0, 2))
        rng = np.random.default_rng(1000003 + 7919 * c + 31 * len(self.obs[c])
                                   + 17 * len(self.negatives.get(c, [])))
        pts = []
        tries = 0
        while len(pts) < self.n_samples and tries < 25 * self.n_samples:
            tries += 1
            r = radius * math.sqrt(rng.random())
            th = rng.uniform(0, 2 * math.pi)
            q = np.asarray(center, float) + r * np.array([math.cos(th), math.sin(th)])
            if _inside_convex(poly, q):
                pts.append(q)
        return np.asarray(pts, float) if pts else np.zeros((0, 2))

    @staticmethod
    def _explains(g, negs, R, theta):
        v = np.array([math.cos(theta), math.sin(theta)])
        for p in negs:
            if float(np.linalg.norm(g - p)) > R:
                continue
            if float((p - g) @ v) < -1e-9:
                continue
            return False
        return True

    def _consistent(self, samples, negs):
        if not len(samples) or not negs:
            return samples
        thetas = np.linspace(0, 2 * math.pi, 24, endpoint=False)
        keep = []
        for g in samples:
            ok = False
            for R in (1000., 1250., 1500.):
                for th in thetas:
                    if self._explains(g, negs, R, th):
                        ok = True
                        break
                if ok:
                    break
            if ok:
                keep.append(g)
        return np.asarray(keep, float) if keep else np.zeros((0, 2))

    def _filtered_samples(self, c):
        samples = self._hypothesis_samples(c)
        self.diagnostics['pred_calls'] += 1
        self.diagnostics['pred_samples_total'] += len(samples)
        out = self._consistent(samples, self.negatives.get(c, []))
        self.diagnostics['pred_samples_kept'] += len(out)
        return out

    # ---- ordering only -------------------------------------------------
    def _order_by_mass(self, c, points):
        """Greedy order of the SAME points by how much filtered mass they finish."""
        if not self.use_prediction or len(points) < 2:
            return list(range(len(points)))
        samples = self._filtered_samples(c)
        if not len(samples):
            return list(range(len(points)))
        remaining = np.ones(len(samples), bool)
        order = []
        left = set(range(len(points)))
        while left:
            best, best_mass = None, -1
            for j in left:
                mass = int((np.linalg.norm(samples - np.asarray(points[j], float), axis=1)[remaining] <= 20.).sum())
                if mass > best_mass:
                    best, best_mass = j, mass
            order.append(best)
            left.discard(best)
            remaining &= ~(np.linalg.norm(samples - np.asarray(points[best], float), axis=1) <= 20.)
        self.diagnostics['pred_reorders'] += 1
        return order

    def directional_fallback(self, c):
        poly, center, radius = self.region(c)
        if radius <= 19.99:
            self.certified_clear(c, poly, center, radius)
            return
        self.counts['fallback'] += 1
        from geometry import optical_cover
        from solver import open_route
        pts = optical_cover(poly, self.obs[c][0][1])
        order = self._order_by_mass(c, pts)
        for j in order:
            if self.clear(pts[j], c):
                return
        raise RuntimeError('Exhausted optical cover')

    def directional_options(self, c, poly, center, radius):
        from active_localization import ActiveLocalizationSolver
        opts = ActiveLocalizationSolver.directional_options(self, c, poly, center, radius)
        if not self.use_prediction or len(opts) < 2:
            return opts
        samples = self._filtered_samples(c)
        if not len(samples):
            return opts
        scored = []
        for q in opts:
            q = np.asarray(q, float)
            mass = int((np.linalg.norm(samples - q, axis=1) <= 20.).sum())
            scored.append((mass, -float(np.linalg.norm(q - self.pos)), q))
        scored.sort(key=lambda t: (-t[0], -t[1]))
        return [q for _, _, q in scored]
