"""N6 arm: analytic (continuous theta, R-interval) state construction for Q4.

Only ``_state_records`` is replaced. Positions come from the same stratified sampler,
the candidate/score logic (C2 option scoring) is byte-identical, so the comparison
isolates the state representation. R is never pinned to L: each record draws R
uniformly from the analytic feasible interval [L, hi(theta)).

Diagnostics
    n6_positions / n6_infeasible          : position-level existence results
    n6_omni, n6_directional               : which branch survived
    n6_disagree_grid_feasible_analytic_no : finite-grid model accepted a position the
                                            analytic model rejects (grid over-accepts)
    n6_disagree_analytic_feasible_grid_no : the reverse (grid under-accepts)
    n6_theta_width_mean                   : mean total feasible heading arc (rad)
"""
import numpy as np

from analytic_state import R_MAX, analyse_position
from state_prediction import JointStatePrediction


class JointAnalyticState(JointStatePrediction):
    def __init__(self, *args, n6_r_samples=2, **kwargs):
        super().__init__(*args, **kwargs)
        self.n6_r_samples = int(n6_r_samples)
        self.diagnostics.update(n6_positions=0, n6_infeasible=0, n6_omni=0, n6_directional=0,
                                n6_disagree_grid_feasible_analytic_no=0,
                                n6_disagree_analytic_feasible_grid_no=0,
                                n6_theta_width_mean=0., n6_records=0)
        self._grid_feasible_cache = {}

    # -- finite-grid reference verdict on the same position -----------------
    def _grid_feasible(self, c, g):
        positives = [(np.asarray(p, float), float(a)) for p, a in self.obs[c]]
        negatives = [np.asarray(p, float) for p in self.negatives.get(c, [])]
        dist_p = np.asarray([float(np.linalg.norm(p - g)) for p, _ in positives], float)
        dist_n = np.asarray([float(np.linalg.norm(q - g)) for q in negatives], float)
        for R in (1000., 1250., 1500.):
            if (len(dist_p) == 0 or float(dist_p.max()) <= R) and \
               (len(dist_n) == 0 or float(dist_n.min()) > R):
                return True
        if not self.c2_enabled:
            return True
        from state_prediction import BEARING_TOL_DEG, THETA_BINS
        import math
        thetas = np.linspace(0, 2 * math.pi, THETA_BINS, endpoint=False)
        cos, sin = np.cos(thetas), np.sin(thetas)
        for R in (1000., 1250., 1500.):
            front = np.ones(THETA_BINS, bool)
            for p, _a in positives:
                d = np.asarray(p, float) - g
                if float(np.linalg.norm(d)) > R:
                    front[:] = False
                    break
                front &= (d[0] * cos + d[1] * sin) >= -1e-9
            back = np.ones(THETA_BINS, bool)
            for q in negatives:
                d = np.asarray(q, float) - g
                dist = float(np.linalg.norm(d))
                if dist > R:
                    continue
                back &= ((g - np.asarray(q, float))[0] * cos
                         + (g - np.asarray(q, float))[1] * sin) > 1e-9
            if bool((front & back).any()):
                return True
        return False

    # -- analytic state construction ---------------------------------------
    def _state_records(self, c):
        samples = self._hypothesis_samples(c)
        self.diagnostics['pred_calls'] += 1
        self.diagnostics['pred_samples_total'] += len(samples)
        if not len(samples):
            return []
        positives = [(np.asarray(p, float), float(a)) for p, a in self.obs[c]]
        negatives = [np.asarray(p, float) for p in self.negatives.get(c, [])]
        rng = np.random.default_rng(424242 + 7919 * c + 31 * len(self.obs[c])
                                    + 17 * len(negatives))
        records = []
        width_sum = 0.
        for g in samples:
            self.diagnostics['n6_positions'] += 1
            st = analyse_position(g, positives, negatives)
            grid_ok = self._grid_feasible(c, g)
            if not st.feasible:
                self.diagnostics['n6_infeasible'] += 1
                if grid_ok:
                    self.diagnostics['n6_disagree_grid_feasible_analytic_no'] += 1
                continue
            if not grid_ok:
                self.diagnostics['n6_disagree_analytic_feasible_grid_no'] += 1
            if st.kind == 'omni':
                self.diagnostics['n6_omni'] += 1
                records.append((np.asarray(g, float), st.L, 'omni', 0.))
                self.diagnostics['n6_records'] += 1
                continue
            self.diagnostics['n6_directional'] += 1
            width_sum += sum(hi - lo for lo, hi in st.theta_intervals)
            for theta in st.theta_representatives(k=2):
                lo, hi, open_hi = st.radius_interval(theta)
                if hi <= lo + 1e-9:
                    continue
                for _ in range(max(1, self.n6_r_samples)):
                    R = float(rng.uniform(lo, hi if not open_hi else hi - 1e-6))
                    records.append((np.asarray(g, float), R, 'direction', float(theta)))
                    self.diagnostics['n6_records'] += 1
        if self.diagnostics['n6_directional']:
            self.diagnostics['n6_theta_width_mean'] += width_sum / self.diagnostics['n6_directional']
        if len(records) > 240:
            step = max(1, len(records) // 240)
            records = records[::step][:240]
        return records
