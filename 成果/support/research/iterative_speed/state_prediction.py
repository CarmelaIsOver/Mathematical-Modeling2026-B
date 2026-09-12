"""Direction C: joint positive/negative observation state prediction for Q4.

C1 - fallback ordering by *mean first-hit time*
    Each hypothesis sample gets the time at which it first falls inside the 20 m clear
    range of a visited point, charged as the backend does (movement 1 s / 5 m, 3 s
    optical attempt, +2 s on success). The order is chosen to minimise
    ``mean + 0.5 * (p95 - mean)``; the baseline order is kept whenever the model does
    not predict an advantage. All fallback points are preserved - only the order
    changes.

C2 - joint (g, R, type, theta) consistency
    Candidates keep the full tuple: position sample g, receivable radius R, source
    type (omni or directional) and emission direction theta. A tuple survives only if
    it explains *all* positive receptions and *all* recorded no_signal readings:
      positive (p, bearing) : |p-g| <= R and, for directional, (p-g).v(theta) >= 0
      no_signal p           : |p-g| > R or (p-g).v(theta) < 0
    Tuples are used for prediction and ranking only: they never delete the certified
    feasible region, never declare a channel absent and never issue a clear
    certificate. If no tuple survives, the baseline order is used unchanged.
"""
import math

import numpy as np

from joint_search import JointSearchSolver

CLEAR_RANGE = 20.
R_GRID = (1000., 1250., 1500.)
THETA_BINS = 24
MAX_RECORDS = 240
# Documented bounded measurement error of the bearing interface (+/-1 degree); the
# joint state must explain every positive bearing within this cone, and a no_signal
# is judged with the same margin.
BEARING_TOL_DEG = 1.0


def _inside_convex(poly, q, eps=1e-9):
    n = len(poly)
    if n < 3:
        return True
    pos = neg = False
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        cross = (b[0] - a[0]) * (q[1] - a[1]) - (b[1] - a[1]) * (q[0] - a[0])
        if cross > eps:
            pos = True
        elif cross < -eps:
            neg = True
        if pos and neg:
            return False
    return True


class JointStatePrediction(JointSearchSolver):
    def __init__(self, *args, n_samples=64, use_prediction=True, mode='c1', **kwargs):
        super().__init__(*args, **kwargs)
        self.n_samples = int(n_samples)
        self.use_prediction = bool(use_prediction)
        self.mode = mode                       # 'c1' | 'c2' | 'both' (isolated tests)
        self.c2_enabled = mode in ('c2', 'both')
        self.c1_enabled = mode in ('c1', 'both')
        self.negatives = {}
        self.diagnostics.update(pred_negatives=0, pred_calls=0, pred_samples_kept=0,
                                pred_samples_total=0, pred_records=0, pred_reorders=0,
                                pred_gate_rejections=0, pred_predicted_gain_s=0.,
                                pred_pred_calls=0, pred_omni_records=0,
                                pred_dir_records=0, pred_measure_scored=0,
                                pred_option_gain_s=0., pred_option_calls=0)

    # ---- observation bookkeeping ---------------------------------------
    def action(self, path, p, c):
        r = super().action(path, p, c)
        if path == '/measure' and r['measure_result'] == 'no_signal':
            self.negatives.setdefault(c, []).append(np.asarray(p, float))
            self.diagnostics['pred_negatives'] += 1
        return r

    # ---- hypothesis sampling -------------------------------------------
    def _hypothesis_samples(self, c):
        """Hypothesis positions by explicit stratification (design distribution).

        * No positive reception: area-proportional stratified sampling. The convex
          posterior is triangulated as a fan; each triangle gets samples proportional
          to its area and each sample is drawn sqrt-uniformly inside its triangle.
          The polygon vertices are added as a separate extreme stratum.
        * With positive receptions: the +/-1 deg cone is kept, stratified along the
          distance interval so enumeration order cannot decide the weights.

        This is a declared design distribution for planning only - never an official
        posterior and never a certificate.
        """
        poly, center, radius = self.region(c)
        if radius <= 1e-9 or len(poly) < 3:
            return np.zeros((0, 2))
        positives = [(np.asarray(p, float), float(a)) for p, a in self.obs[c]]
        rng = np.random.default_rng(1000003 + 7919 * c + 31 * len(self.obs[c])
                                   + 17 * len(self.negatives.get(c, [])))
        tol = math.radians(BEARING_TOL_DEG)
        pts = []
        if positives:
            n = self.n_samples
            for i in range(n):
                p0, ang = positives[int(rng.integers(len(positives)))]
                d_lo, d_hi = 1500. * i / n, 1500. * (i + 1) / n
                dist = float(rng.uniform(d_lo, d_hi))
                delta = rng.uniform(-tol, tol)
                q = p0 + dist * np.array([math.cos(math.radians(ang) + delta),
                                          math.sin(math.radians(ang) + delta)])
                if _inside_convex(poly, q):
                    pts.append(q)
            return np.asarray(pts, float) if pts else np.zeros((0, 2))
        # area-proportional stratified fan triangulation
        v0 = poly[0]
        tris = [(v0, poly[i], poly[i + 1]) for i in range(1, len(poly) - 1)]
        areas = np.asarray([abs((b[0] - a[0]) * (cpt[1] - a[1]) - (b[1] - a[1]) * (cpt[0] - a[0])) / 2.
                            for a, b, cpt in tris], float)
        total = float(areas.sum())
        if total <= 1e-12:
            return np.zeros((0, 2))
        budget = max(0, self.n_samples - min(len(poly), 4))     # reserve the extreme stratum
        alloc = np.floor(areas / total * budget).astype(int)
        for i in range(budget - int(alloc.sum())):
            alloc[int(np.argmax(areas - alloc))] += 1
        for (a, b, cpt), k in zip(tris, alloc):
            for _ in range(int(k)):
                r1, r2 = math.sqrt(rng.random()), rng.random()
                pts.append(a + r1 * (1 - r2) * (b - a) + r1 * r2 * (cpt - a))
        for v in poly[:4]:
            pts.append(np.asarray(v, float))
        return np.asarray(pts, float) if pts else np.zeros((0, 2))


    def _state_records(self, c):
        """Feasible (g, R, type, theta) records explaining every public observation."""
        samples = self._hypothesis_samples(c)
        self.diagnostics['pred_calls'] += 1
        self.diagnostics['pred_samples_total'] += len(samples)
        if not len(samples):
            return []
        if not self.c2_enabled:
            # C1 isolation: use the raw posterior samples as planning hypotheses; the
            # joint R/type/theta filtering is switched off.
            self.diagnostics['pred_samples_kept'] += len(samples)
            self.diagnostics['pred_records'] += len(samples)
            return [(g, R_GRID[0], 'omni', 0) for g in samples]
        positives = [(np.asarray(p, float), float(a)) for p, a in self.obs[c]]
        negatives = [np.asarray(p, float) for p in self.negatives.get(c, [])]
        thetas = np.linspace(0, 2 * math.pi, THETA_BINS, endpoint=False)
        cos, sin = np.cos(thetas), np.sin(thetas)
        records = []
        per_pos = max(1, MAX_RECORDS // max(1, len(samples)))
        for g in samples:
            before = len(records)
            dist_p = np.asarray([float(np.linalg.norm(q - g)) for q, _ in positives], float)
            dist_n = np.asarray([float(np.linalg.norm(q - g)) for q in negatives], float)
            for R in R_GRID:
                # omni: no orientation constraint at all
                if (len(dist_p) == 0 or float(dist_p.max()) <= R) and \
                   (len(dist_n) == 0 or float(dist_n.min()) > R):
                    records.append((g, R, 'omni', 0))
                    self.diagnostics['pred_omni_records'] += 1
                if self.c2_enabled:
                    # Strict physics: the +/-1 deg bound constrains only the observed
                    # bearing versus the source position. The emission half-plane is
                    # NOT widened; float tolerance only.
                    front_ok = np.ones(THETA_BINS, bool)
                    for p, ang_obs in positives:
                        d = np.asarray(p, float) - g
                        dist_pg = float(np.linalg.norm(d))
                        if dist_pg > R:
                            front_ok[:] = False
                            break
                        # (a) the observed bearing must match within the bounded error
                        ang_g = math.degrees(math.atan2(g[1] - p[1], g[0] - p[0])) % 360.
                        diff = abs((ang_g - float(ang_obs) + 180.) % 360. - 180.)
                        if diff > BEARING_TOL_DEG:
                            front_ok[:] = False
                            break
                        # (b) strict visibility half-plane
                        u = d / max(dist_pg, 1e-9)
                        front_ok &= (u[0] * cos + u[1] * sin) >= -1e-9
                    back_ok = np.ones(THETA_BINS, bool)
                    for p in negatives:
                        d = g - np.asarray(p, float)
                        dist_n_p = float(np.linalg.norm(np.asarray(p, float) - g))
                        if dist_n_p > R:
                            continue          # out of range hides the source for any theta
                        u = d / max(dist_n_p, 1e-9)
                        # not visible <=> (p-g).v < 0, strictly (float tolerance only)
                        back_ok &= (u[0] * cos + u[1] * sin) > 1e-9
                    ok = front_ok & back_ok
                    for idx in np.where(ok)[0]:
                        if len(records) - before >= per_pos:
                            break
                        records.append((g, R, 'direction', float(thetas[idx])))
                        self.diagnostics['pred_dir_records'] += 1
                if len(records) - before >= per_pos:
                    break
            if len(records) >= MAX_RECORDS:
                break
        self.diagnostics['pred_samples_kept'] += len({id(r[0]) for r in records} or [])
        self.diagnostics['pred_records'] += len(records)
        return records

    # ---- C1: mean first-hit time ---------------------------------------
    def _first_hit_stats(self, samples, points, order, include_attempt_cost=True, exit_point=None):
        """(mean, p95) of the time each sample first enters the clear range.

        The departure leg after a successful clear is included when ``exit_point`` is
        given: a sample first hit at point j is charged the movement from that point to
        the next retained task, because the mission has to leave the clear site anyway.
        """
        if not len(samples) or not len(points):
            return 0., 0.
        remaining = np.ones(len(samples), bool)
        hits = np.zeros(len(samples), float)
        cur = np.asarray(self.pos, float)
        t = 0.
        for j in order:
            pt = np.asarray(points[j], float)
            t += float(np.linalg.norm(pt - cur)) / 5
            cur = pt
            if include_attempt_cost:
                t += 3.
            exit_s = (0. if exit_point is None
                      else float(np.linalg.norm(pt - np.asarray(exit_point, float))) / 5)
            inside = np.linalg.norm(samples - pt, axis=1) <= CLEAR_RANGE
            newly = inside & remaining
            hits[newly] = t + (2. if include_attempt_cost else 0.) + exit_s
            remaining &= ~inside
            if not remaining.any():
                break
        if remaining.any():
            hits[remaining] = t + (0. if include_attempt_cost else 0.)
        return float(hits.mean()), float(np.percentile(hits, 95))

    @staticmethod
    def _score_from_stats(stats):
        mean, p95 = stats
        return mean + .5 * (p95 - mean)

    def _next_task_point(self, c):
        pts = [self.stations[i] for i in self.pending_stations]
        for k in self.deferred:
            if k == c:
                continue
            try:
                pts.append(self.region(k)[1])
            except Exception:
                pass
        if not pts:
            return None
        arr = np.asarray(pts, float)
        return arr[int(np.argmin(np.linalg.norm(arr - self.pos, axis=1)))]

    def _order_by_first_hit(self, c, points):
        if not self.use_prediction or len(points) < 2:
            return list(range(len(points)))
        from solver import open_route
        baseline_order = list(open_route(points, self.pos))
        exit_point = self._next_task_point(c)
        records = self._state_records(c)
        samples = np.asarray([r[0] for r in records], float) if records else np.zeros((0, 2))
        if not len(samples):
            return baseline_order
        base_stats = self._first_hit_stats(samples, points, baseline_order, exit_point=exit_point)
        # greedy: repeatedly append the point that minimises the running score
        order, rest = [], list(range(len(points)))
        cur = np.asarray(self.pos, float)
        t = 0.
        remaining = np.ones(len(samples), bool)
        hits = np.zeros(len(samples), float)
        while rest:
            best, best_score = None, None
            for j in rest:
                pt = np.asarray(points[j], float)
                step = float(np.linalg.norm(pt - cur)) / 5 + 3.
                cand_hits = hits.copy()
                exit_s = (0. if exit_point is None
                          else float(np.linalg.norm(pt - np.asarray(exit_point, float))) / 5)
                inside = np.linalg.norm(samples - pt, axis=1) <= CLEAR_RANGE
                newly = inside & remaining
                cand_hits[newly] = t + step + 2. + exit_s
                cand_remaining = remaining & ~inside
                if cand_remaining.any():
                    cand_hits[cand_remaining] = t + step
                score = self._score_from_stats((float(cand_hits.mean()),
                                                float(np.percentile(cand_hits, 95))))
                if best_score is None or score < best_score:
                    best, best_score = j, score
            pt = np.asarray(points[best], float)
            t += float(np.linalg.norm(pt - cur)) / 5 + 3.
            cur = pt
            inside = np.linalg.norm(samples - pt, axis=1) <= CLEAR_RANGE
            newly = inside & remaining
            hits[newly] = t + 2.
            remaining &= ~inside
            order.append(best)
            rest.remove(best)
        cand_stats = self._first_hit_stats(samples, points, order, exit_point=exit_point)
        gain = self._score_from_stats(base_stats) - self._score_from_stats(cand_stats)
        self.diagnostics['pred_predicted_gain_s'] += float(gain)
        self.diagnostics['pred_pred_calls'] += 1
        # Safety margin: the measured prediction error of this model is far larger
        # than a 1 s gain (screen r76: predicted +0.8 s, realised -237 s), so a
        # reorder is only taken when the predicted advantage exceeds max(5 s, 1 %)
        # of the baseline score. Single documented margin, not a swept threshold.
        margin = max(5., .01 * self._score_from_stats(base_stats))
        if gain <= margin:
            self.diagnostics['pred_gate_rejections'] += 1
            return baseline_order
        self.diagnostics['pred_reorders'] += 1
        return order

    # ---- entry points ---------------------------------------------------
    def directional_fallback(self, c):
        poly, center, radius = self.region(c)
        if radius <= 19.99:
            self.certified_clear(c, poly, center, radius)
            return
        self.counts['fallback'] += 1
        from geometry import optical_cover
        from solver import open_route
        pts = optical_cover(poly, self.obs[c][0][1])
        order = self._order_by_first_hit(c, pts) if self.c1_enabled else list(open_route(pts, self.pos))
        for j in order:
            if self.clear(pts[j], c):
                return
        raise RuntimeError('Exhausted optical cover')

    def _score_option(self, c, q, center, radius, records):
        """Same-scale service score for one measurement candidate."""
        q = np.asarray(q, float)
        costs = []
        for g, R, kind, theta in records:
            d = g - q
            dist = float(np.linalg.norm(d))
            receivable = dist <= R and (kind == 'omni'
                                        or float(d[0] * math.cos(theta) + d[1] * math.sin(theta)) <= 0.)
            if receivable:
                # a bearing from q roughly splits the posterior: follow-up leg to the
                # posterior centre plus one measure, then half a radius of residual walk
                costs.append(dist / 5 + 5. + .5 * float(radius) / 5)
            else:
                costs.append(float(np.linalg.norm(q - np.asarray(center, float))) / 5 + 5.
                             + .5 * float(radius) / 5)
        costs = np.asarray(costs, float)
        base = float(np.linalg.norm(q - self.pos)) / 5 + 5. + int(c != self.channel)
        return base + float(costs.mean()) + .5 * float(costs.max() - costs.mean())

    def directional_options(self, c, poly, center, radius):
        """Score candidates by predicted reception and subsequent localization cost."""
        from active_localization import ActiveLocalizationSolver
        opts = ActiveLocalizationSolver.directional_options(self, c, poly, center, radius)
        if not self.use_prediction or not self.c2_enabled or len(opts) < 2:
            return opts
        records = self._state_records(c)
        if not records:
            return opts
        scored = []
        for q in opts:
            scored.append((self._score_option(c, q, center, radius, records), np.asarray(q, float)))
            self.diagnostics['pred_measure_scored'] += 1
        scored.sort(key=lambda t: t[0])
        # same-scale prediction record: baseline option vs best option
        baseline_score = self._score_option(c, opts[0], center, radius, records)
        self.diagnostics['pred_option_gain_s'] += float(baseline_score - scored[0][0])
        self.diagnostics['pred_option_calls'] += 1
        return [q for _, q in scored]
