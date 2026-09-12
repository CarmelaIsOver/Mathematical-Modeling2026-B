"""N1: complete hypothesised-world continuation for the Q3 measurement decision.

Every candidate action is executed in the SAME fixed set of physically consistent
worlds and then continued to clearance by the same baseline policy. Nothing here
reads the real backend: worlds are built from the public posterior only, and the
continuation policy sees nothing but the feedback the world produces.

World:  (g, R, omni) with g an area-stratified posterior sample, R in [L(g), 1500]
        where L(g) = max(1000, max positive-observation distance to g); L(g) > 1500
        makes the world infeasible and it is dropped.
Error:  one of the declared fixed rules - zero, global +1 deg, or a position/channel
        hashed offset in [-1, 1]. Same world + position + channel always returns the
        same reading, so repeated measurements never create new information.

Cost model (charged exactly as the backend does):
        movement 1 s / 5 m, 5 s per measure, 1 s per channel switch,
        3 s per optical attempt, +2 s on a successful clear, plus the closing leg
        from the end position to the retained next obligation z.

A candidate whose world is not cleared after the bounded rounds AND the full optical
fallback is marked incomplete and rejected - never charged as if it had cleared.
"""
import hashlib
import math

import numpy as np

from active_localization import radius_bound
from geometry import bearing_clip, enclosing_circle, feasible, optical_cover, EPS_DEG
from solver import Solver, open_route, safe_clear_point


def _poly_signature(poly):
    if not len(poly):
        return ()
    return tuple(sorted((round(float(p[0]), 1), round(float(p[1]), 1)) for p in poly))


class WorldRolloutMixin:
    def _setup_rollout(self, rollout_radius=400., n_worlds=12, max_rounds=6, lam=.5,
                       mode='service', opt_penalty=60., margin_s=0., margin_frac=0.):
        self.rollout_radius = float(rollout_radius)
        self.rollout_worlds = int(n_worlds)
        self.rollout_rounds = int(max_rounds)
        self.rollout_lam = float(lam)
        self.rollout_mode = mode
        self.rollout_penalty = float(opt_penalty)
        # Revision r1: only deviate from the baseline when the predicted advantage
        # exceeds the measured resolution of the rollout (same-state MAE ~3.5 s).
        self.rollout_margin_s = float(margin_s)
        self.rollout_margin_frac = float(margin_frac)
        self.diagnostics.update(rollout_calls=0, rollout_active=0, rollout_changed=0,
                                rollout_worlds=0, rollout_incomplete=0,
                                rollout_cache_hits=0, rollout_pred_adopted_s=0.,
                                rollout_pred_calls=0)
        # per-decision picks for the offline same-state counterfactual (dev data)
        self.diagnostics['rollout_picks'] = []
        self.diagnostics['rollout_pred_log'] = []

    def _base_pick(self, c, poly, center, radius):
        """Strong-baseline measurement pick for Q3 (Solver's own rule)."""
        return Solver.next_measure(self, c, poly, center, radius)

    # ---- worlds ---------------------------------------------------------
    def _world_set(self, c):
        poly, center, radius = self.region(c)
        if len(poly) < 3 or radius <= 1e-9:
            return []
        rng = np.random.default_rng(20260913 + 7919 * c + 31 * len(self.obs[c]))
        samples = self._stratified_positions(poly, self.rollout_worlds, rng)
        worlds = []
        rules = ('zero', 'global1', 'hash')
        for i, g in enumerate(samples):
            L = 1000.
            for p, _a in self.obs[c]:
                L = max(L, float(np.linalg.norm(np.asarray(p, float) - g)))
            if L > 1500.:
                continue                       # no receivable radius explains the history
            R = float(rng.uniform(L, 1500.)) if L < 1500. else 1500.
            worlds.append((np.asarray(g, float), R, rules[i % len(rules)]))
        self.diagnostics['rollout_worlds'] += len(worlds)
        return worlds

    def _stratified_positions(self, poly, n, rng):
        """Area-proportional fan stratification plus the vertex extreme stratum."""
        v0 = poly[0]
        tris = [(v0, poly[i], poly[i + 1]) for i in range(1, len(poly) - 1)]
        areas = []
        for a, b, cp in tris:
            areas.append(abs((b[0] - a[0]) * (cp[1] - a[1]) - (b[1] - a[1]) * (cp[0] - a[0])) / 2.)
        areas = np.asarray(areas, float)
        total = float(areas.sum())
        if total <= 1e-12:
            return []
        budget = max(0, n - min(len(poly), 3))
        pts = []
        for (a, b, cp), frac in zip(tris, areas / total):
            k = int(round(frac * budget))
            for _ in range(k):
                r1, r2 = math.sqrt(rng.random()), rng.random()
                pts.append(a + r1 * (1 - r2) * (b - a) + r1 * r2 * (cp - a))
        for v in poly[:3]:
            pts.append(np.asarray(v, float))
        return pts[:max(1, n)]

    # ---- world physics --------------------------------------------------
    @staticmethod
    def _world_error(rule, g, q, c):
        if rule == 'zero':
            return 0.
        if rule == 'global1':
            return 1.0
        key = f'{rule}:{c}:{round(float(q[0]), 3)}:{round(float(q[1]), 3)}'
        h = hashlib.sha256(key.encode()).digest()
        return (int.from_bytes(h[:4], 'big') / 2 ** 32) * 2. - 1.

    def _feedback(self, world, q, c):
        g, R, rule = world
        q = np.asarray(q, float)
        d = float(np.linalg.norm(q - g))
        if d > R:
            return 'no_signal', None
        if d <= 5.:
            return 'near', None
        bearing = math.degrees(math.atan2(g[1] - q[1], g[0] - q[0])) % 360.
        return 'direction', (bearing + self._world_error(rule, g, q, c)) % 360.

    def _apply_feedback(self, poly, q, kind, bearing):
        if kind == 'no_signal':
            return poly
        if kind == 'direction':
            post = bearing_clip(poly, q, bearing, EPS_DEG)
            return post if len(post) else None
        return np.zeros((0, 2))                 # near -> cleared at q

    def _fallback_points(self, poly, sample_dir):
        return list(optical_cover(poly, sample_dir))

    # ---- one world rollout ---------------------------------------------
    def _rollout(self, c, world, first):
        """Charged cost in one world for taking ``first`` now, then the baseline.

        ``first`` is a measurement point or the string 'optical' (execute the whole
        finite optical fallback immediately). Returns (cost, cleared, note).
        """
        poly, center, radius = self.region(c)
        g = world[0]
        pos = np.asarray(self.pos, float)
        channel = int(self.channel)
        t = 0.
        measured = set()
        for p in self.measured[c]:
            measured.add((round(float(p[0]), 2), round(float(p[1]), 2)))
        hist = [(np.asarray(p, float), float(a)) for p, a in self.obs[c]]
        z = self._rollout_exit(c, poly)

        def measure(q):
            nonlocal t, pos, channel, poly
            q = np.asarray(q, float)
            t += float(np.linalg.norm(q - pos)) / 5 + 5. + int(c != channel)
            pos, channel = q, int(c)
            measured.add((round(float(q[0]), 2), round(float(q[1]), 2)))
            kind, bearing = self._feedback(world, q, c)
            if kind == 'direction':
                hist.append((q, float(bearing)))
            poly = self._apply_feedback(poly, q, kind, bearing)
            return kind

        # 1) the candidate action
        if isinstance(first, str) and first == 'optical':
            for p in self._fallback_points(poly, self.obs[c][0][1]):
                t += float(np.linalg.norm(p - pos)) / 5
                pos = np.asarray(p, float)
                t += 3.
                if float(np.linalg.norm(pos - g)) <= 20.:
                    t += 2.
                    return t + self._leg(pos, z), True, 'optical'
            return t + self._leg(pos, z), False, 'optical-exhausted'
        kind = measure(first)
        if kind == 'near':
            t += 3. + 2.                            # clear at the measurement point
            return t + self._leg(pos, z), True, 'near'

        # 2) same baseline policy continues, reading only the generated feedback
        rounds = 0
        while rounds < self.rollout_rounds and poly is not None and len(poly) >= 3:
            rb, mb = radius_bound(poly)
            if rb <= 19.99:
                break
            q = self._baseline_pick(c, poly, mb, rb, pos, channel, measured, hist)
            if q is None:
                break
            rounds += 1
            before = poly
            kind = measure(q)
            if kind == 'near':
                t += 3. + 2.
                return t + self._leg(pos, z), True, 'near'
            if poly is None:
                poly = before                      # inconsistent world: keep the set
                continue
        rb, mb = radius_bound(poly) if poly is not None and len(poly) else (1e9, np.zeros(2))
        if poly is not None and len(poly) >= 3 and rb <= 19.99:
            cp = np.asarray(safe_clear_point(pos, mb, rb), float)
            t += float(np.linalg.norm(cp - pos)) / 5 + 3. + 2.
            return t + self._leg(cp, z), True, 'certified'
        # 3) executable finite fallback; if it still misses, the candidate is rejected
        for p in self._fallback_points(poly if poly is not None and len(poly) >= 3
                                       else self.region(c)[0], self.obs[c][0][1]):
            t += float(np.linalg.norm(p - pos)) / 5
            pos = np.asarray(p, float)
            t += 3.
            if float(np.linalg.norm(pos - g)) <= 20.:
                t += 2.
                return t + self._leg(pos, z), True, 'fallback'
        return t + self._leg(pos, z), False, 'fallback-exhausted'

    def _leg(self, pos, z):
        return 0. if z is None else float(np.linalg.norm(np.asarray(pos, float) - np.asarray(z, float))) / 5

    def _rollout_exit(self, c, poly):
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

    @staticmethod
    def _baseline_pick(c, poly, center, radius, pos, channel, measured, hist):
        """Baseline measurement rule on a lightweight assumed state.

        The state carries the real public history plus the feedback this world has
        produced so far; it never touches the controller and never sees the world.
        """
        class _S:
            pass
        st = _S()
        st.pos = np.asarray(pos, float)
        st.channel = int(channel)
        st.problem = 3
        st.obs = {c: [(np.asarray(p, float), float(a)) for p, a in hist]}
        st.measured = {c: [np.asarray(p, float) for p in measured]}
        st.diagnostics = {'candidate_evaluations': 0}
        try:
            return Solver.next_measure(st, c, poly, center, radius)
        except Exception:
            return np.asarray(center, float)

    # ---- decision -------------------------------------------------------
    def _rollout_candidates(self, c, poly, center, radius):
        base = self._base_pick(c, poly, center, radius)
        cands = []
        if base is not None:
            cands.append(np.asarray(base, float))
        cands.append(np.asarray(self.pos, float))
        rng = np.random.default_rng(7 + 13 * c + len(self.obs[c]))
        cands.extend(self._stratified_positions(poly, 3, rng))
        nxt = self._rollout_exit(c, poly)
        if nxt is not None:
            d = np.asarray(nxt, float) - self.pos
            n = float(np.linalg.norm(d))
            if n > 1e-6:
                cands.append(self.pos + min(150., n) * d / n)
        out, seen = [], set()
        for q in cands:
            q = np.asarray(q, float)
            key = (round(float(q[0]), 2), round(float(q[1]), 2))
            if key in seen:
                continue
            if any(float(np.linalg.norm(q - p)) < .1 for p in self.measured[c]):
                continue
            seen.add(key)
            out.append(q)
        return out

    def next_measure(self, c, poly, center, radius):
        self.diagnostics['rollout_calls'] += 1
        if self.rollout_mode == 'off' or radius > self.rollout_radius:
            return self._base_pick(c, poly, center, radius)
        base = self._base_pick(c, poly, center, radius)
        worlds = self._world_set(c)
        if not worlds:
            return base
        self.diagnostics['rollout_active'] += 1
        cands = self._rollout_candidates(c, poly, center, radius) + ['optical']
        scored = []
        for q in cands:
            costs, cleared = [], 0
            for w in worlds:
                cost, ok, _note = self._rollout(c, w, q)
                if not ok:
                    self.diagnostics['rollout_incomplete'] += 1
                    continue
                costs.append(cost)
                cleared += 1
            if len(costs) < max(1, int(.6 * len(worlds))):
                continue                       # too many worlds never cleared: reject
            costs = np.asarray(costs, float)
            score = float(costs.mean()) + self.rollout_lam * float(costs.max() - costs.mean())
            scored.append((score, q))
        if not scored:
            return base
        scored.sort(key=lambda t: t[0])
        best = scored[0][1]
        base_score = next((s for s, q in scored
                           if isinstance(q, str) is False and base is not None
                           and float(np.linalg.norm(np.asarray(q, float) - np.asarray(base, float))) < .1), None)
        margin = self.rollout_margin_s
        if base_score is not None:
            margin = max(margin, self.rollout_margin_frac * abs(float(base_score)))
        advantage = None if base_score is None else float(base_score - scored[0][0])
        picked = best if isinstance(best, str) is False else base
        if advantage is not None and advantage <= margin:
            picked = base                       # predicted advantage below resolution
        if advantage is not None and advantage > margin:
            self.diagnostics['rollout_pred_adopted_s'] += float(base_score - scored[0][0])
            self.diagnostics['rollout_pred_calls'] += 1
        self.diagnostics['rollout_picks'].append(np.asarray(picked, float).tolist())
        if base_score is not None:
            self.diagnostics['rollout_pred_log'].append({'predicted_saving_s': float(base_score - scored[0][0]),
                                                         'baseline_score_s': float(base_score),
                                                         'best_score_s': float(scored[0][0])})
        else:
            self.diagnostics['rollout_pred_log'].append({'predicted_saving_s': 0.,
                                                         'baseline_score_s': None,
                                                         'best_score_s': float(scored[0][0])})
        if base is not None and float(np.linalg.norm(np.asarray(picked, float) - np.asarray(base, float))) > .1:
            self.diagnostics['rollout_changed'] += 1
        return picked
