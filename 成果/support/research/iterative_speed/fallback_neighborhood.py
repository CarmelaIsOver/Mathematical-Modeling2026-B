"""Q4 fallback capture and finite-neighbourhood ordering study.

Capture (fixed)
    The previous collector compared the public ``fallback`` counter around ``action``
    calls, but the solver increments that counter *before* issuing the first fallback
    action, and the probe was attached to the Q3 arm where the Q4 hook never runs.
    Here the collector sits on the entry of ``directional_fallback`` itself (the Q4
    default strategy) and records the public state *before* the first fallback action:

        position, channel, feasible polygon, incumbent optical order, attempts,
        real movement / optical time spent inside the sweep, exit target

    ``directional_fallback`` behaviour is unchanged: the probe captures and delegates.

Cost model for ordering (same units as the backend)
    movement 1 s / 5 m; failed clear 3 s; successful clear 5 s (3 s optical + 2 s
    laser); exit leg to the retained next obligation. A hypothesis position that is
    never reached inside the candidate order is *not* credited as cleared - the
    candidate is flagged unusable unless the full order is evaluated.

Hypotheses come only from the public feasible region, using a small fixed stratified
design (declared as a design distribution, not an official probability).
"""
import hashlib
import math

import numpy as np

from active_localization import ActiveLocalizationSolver
from geometry import optical_cover
from solver import open_route

CLEAR_RANGE = 20.
FAILED_CLEAR_S = 3.
SUCCESS_CLEAR_S = 5.


def design_positions(poly, center, radius, n=24, seed_key=0):
    """Small fixed stratified design sample inside the public feasible polygon.

    Area-proportional fan stratification (the same declared design used by the other
    research modules): it is a design distribution for ordering only, never a claim
    about the true source and never a certificate.
    """
    poly = np.asarray(poly, float)
    if len(poly) < 3:
        return np.zeros((0, 2))
    rng = np.random.default_rng(20260913 + 13 * int(seed_key))
    v0 = poly[0]
    tris = [(v0, poly[i], poly[i + 1]) for i in range(1, len(poly) - 1)]
    areas = np.asarray([abs((b[0] - a[0]) * (cp[1] - a[1]) - (b[1] - a[1]) * (cp[0] - a[0])) / 2.
                        for a, b, cp in tris], float)
    total = float(areas.sum())
    if total <= 1e-12:
        return np.zeros((0, 2))
    pts = []
    for (a, b, cp), frac in zip(tris, areas / total):
        k = max(1, int(round(frac * n)))
        for _ in range(k):
            r1, r2 = math.sqrt(rng.random()), rng.random()
            pts.append(a + r1 * (1 - r2) * (b - a) + r1 * r2 * (cp - a))
    return np.asarray(pts, float)[:max(1, n)]


def sweep_cost(samples, points, order, start, exit_point=None, movement_only=False):
    """(mean, p95) first-success cost over the design samples for one visit order.

    Returns ``None`` when at least one sample is never reached, because such a
    candidate cannot be credited as a completed sweep.
    """
    if not len(samples) or not len(points):
        return None
    remaining = np.ones(len(samples), bool)
    hit = np.zeros(len(samples), float)
    cur = np.asarray(start, float)
    t = 0.
    for j in order:
        pt = np.asarray(points[j], float)
        t += float(np.linalg.norm(pt - cur)) / 5
        cur = pt
        inside = np.linalg.norm(samples - pt, axis=1) <= CLEAR_RANGE
        newly = inside & remaining
        cost_here = 0. if movement_only else SUCCESS_CLEAR_S
        t_attempt = t + (0. if movement_only else FAILED_CLEAR_S)
        hit[newly] = t_attempt + (cost_here - FAILED_CLEAR_S if not movement_only else 0.)
        t = t_attempt if not movement_only else t
        remaining &= ~inside
        if not remaining.any():
            break
    if remaining.any():
        return None
    if exit_point is not None:
        hit = hit + float(np.linalg.norm(np.asarray(exit_point, float) - cur)) / 5
    return float(hit.mean()), float(np.percentile(hit, 95))


def neighbourhood_orders(incumbent, budget=24):
    """Incumbent plus single moves and pair swaps, capped by a fixed budget."""
    n = len(incumbent)
    out = [list(incumbent)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            cand = list(incumbent)
            v = cand.pop(i)
            cand.insert(j, v)
            out.append(cand)
            if len(out) >= budget:
                return out
    for i in range(n):
        for j in range(i + 1, n):
            cand = list(incumbent)
            cand[i], cand[j] = cand[j], cand[i]
            out.append(cand)
            if len(out) >= budget:
                return out
    return out


class FallbackProbeMixin:
    """Capture fallback entry states and (optionally) reorder the optical sweep."""

    def _setup_fallback(self, capture=True, reorder=False, samples=24, budget=24,
                        margin_s=3.0, margin_frac=0.0, force_order=False):
        self.fb_capture = bool(capture)
        self.fb_reorder = bool(reorder)
        self.fb_samples = int(samples)
        self.fb_budget = int(budget)
        self.fb_margin_s = float(margin_s)
        self.fb_margin_frac = float(margin_frac)
        # force_order: always adopt the best neighbour (even if the incumbent scores
        # better). This guarantees a *differing* order so the same-state comparison
        # measures realised effects instead of repeating the incumbent.
        self.fb_force_order = force_order if isinstance(force_order, str) else bool(force_order)
        self.diagnostics['fallback_rows'] = []
        self.diagnostics.update(fallback_events=0, fallback_captured=0,
                                fallback_attempts=0, fallback_movement_m=0.,
                                fallback_sweep_s=0., fallback_incumbent_s=0.,
                                fb_order_evaluated=0, fb_order_adopted=0,
                                fb_order_predicted_gain_s=0., fallback_exit_m=0.,
                                fallback_clears=0, fallback_cert_clears=0,
                                fb_order_forced_loss_s=0.)
        self._fb_in_sweep = False

    # -- real cost accounting during a sweep ------------------------------
    def clear(self, p, c):
        if getattr(self, '_fb_in_sweep', False):
            moved = float(np.linalg.norm(np.asarray(p, float) - self.pos))
            self.diagnostics['fallback_movement_m'] += moved
            self.diagnostics['fallback_attempts'] += 1
            ok = super().clear(p, c)
            if ok:
                self.diagnostics['fallback_clears'] += 1
            return ok
        return super().clear(p, c)

    # -- the Q4 default strategy entry point ------------------------------
    def directional_fallback(self, c):
        self.diagnostics['fallback_events'] += 1
        if self.fb_capture:
            try:
                self._capture_fallback(c)
                self.diagnostics['fallback_captured'] += 1
            except Exception as exc:                     # noqa: BLE001
                self.diagnostics['fallback_rows'].append({'error': type(exc).__name__ + ': ' + str(exc)[:80]})
        if not self.fb_reorder:
            t0 = float(getattr(self.api, 'virtual_time', 0.))
            self._fb_in_sweep = True
            try:
                result = super().directional_fallback(c)
            finally:
                self._fb_in_sweep = False
                self.diagnostics['fallback_sweep_s'] +=                     float(getattr(self.api, 'virtual_time', 0.)) - t0
            return result
        return self._fallback_with_order(c)

    # -- capture ----------------------------------------------------------
    def _fallback_exit_point(self, c):
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

    def _capture_fallback(self, c):
        poly, center, radius = self.region(c)
        pts = optical_cover(poly, self.obs[c][0][1])
        incumbent = list(open_route(pts, self.pos))
        samples = design_positions(poly, center, radius, self.fb_samples, seed_key=c)
        exit_point = self._fallback_exit_point(c)
        stats = sweep_cost(samples, pts, incumbent, self.pos, exit_point)
        self.diagnostics['fallback_incumbent_s'] += 0. if stats is None else stats[0]
        self.diagnostics['fallback_rows'].append({
            'channel': int(c), 'points': len(pts), 'samples': len(samples),
            'incumbent_mean_s': None if stats is None else round(stats[0], 2),
            'incumbent_p95_s': None if stats is None else round(stats[1], 2),
            'exit_target': None if exit_point is None else [float(exit_point[0]), float(exit_point[1])],
            'incumbent_order': [int(i) for i in incumbent],
            'radius': round(float(radius), 1),
        })

    # -- reorder (only the visit order changes) ---------------------------
    def _fallback_with_order(self, c):
        poly, center, radius = self.region(c)
        if radius <= 19.99:
            return super().directional_fallback(c)
        pts = optical_cover(poly, self.obs[c][0][1])
        if len(pts) < 2:
            return super().directional_fallback(c)
        incumbent = list(open_route(pts, self.pos))
        samples = design_positions(poly, center, radius, self.fb_samples, seed_key=c)
        exit_point = self._fallback_exit_point(c)
        base = sweep_cost(samples, pts, incumbent, self.pos, exit_point)
        best_order, best_stats = incumbent, base
        worst_order, worst_stats = incumbent, None
        margin = self.fb_margin_s
        if base is not None:
            margin = max(margin, self.fb_margin_frac * abs(base[0]))
        for cand in neighbourhood_orders(incumbent, self.fb_budget):
            if cand == incumbent:
                continue
            stats = sweep_cost(samples, pts, cand, self.pos, exit_point)
            self.diagnostics['fb_order_evaluated'] += 1
            if stats is None:
                continue
            if best_stats is None or stats[0] < best_stats[0] - 1e-9:
                best_order, best_stats = cand, stats
            if worst_stats is None or stats[0] > worst_stats[0] + 1e-9:
                worst_order, worst_stats = cand, stats
        predicted = None if (base is None or best_stats is None) else float(base[0] - best_stats[0])
        if self.fb_force_order == 'worst':
            # deliberately take the *worst* neighbour: guarantees a differing order and
            # measures whether the model's ranking direction is real
            if worst_order != incumbent:
                self.diagnostics['fb_order_adopted'] += 1
                if worst_stats is not None and base is not None:
                    self.diagnostics['fb_order_forced_loss_s'] += float(worst_stats[0] - base[0])
                return self._run_order(c, pts, worst_order)
            adopt = False
        elif self.fb_force_order:
            adopt = best_order != incumbent
        else:
            adopt = predicted is not None and predicted > margin
        if adopt:
            self.diagnostics['fb_order_adopted'] += 1
            self.diagnostics['fb_order_predicted_gain_s'] += 0. if predicted is None else predicted
            if predicted is not None and predicted < 0:
                self.diagnostics['fb_order_forced_loss_s'] =                     self.diagnostics.get('fb_order_forced_loss_s', 0.) - predicted
            order = best_order
        else:
            order = incumbent
        return self._run_order(c, pts, order)

    def _run_order(self, c, pts, order):
        self.counts['fallback'] += 1
        t0 = float(getattr(self.api, 'virtual_time', 0.))
        for j in order:
            p = np.asarray(pts[j], float)
            moved = float(np.linalg.norm(p - self.pos)) / 5
            self.diagnostics['fallback_movement_m'] += moved * 5
            self.diagnostics['fallback_attempts'] += 1
            if self.clear(p, c):
                self.diagnostics['fallback_sweep_s'] += float(getattr(self.api, 'virtual_time', 0.)) - t0
                return
        raise RuntimeError('Exhausted optical cover')
