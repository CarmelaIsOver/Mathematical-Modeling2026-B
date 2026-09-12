"""Direction B: constrained rolling insertion with entry-L-service-exit accounting.

The production run loop keeps its coverage backbone and its router. This module only
injects a policy *at the single routing decision point* by temporarily replacing the
module-level ``search_route`` while ``run()`` executes, so the production loop is
reused verbatim (no duplicated scheduler).

Rule: if the router's first node is a coverage station S_next, evaluate each known
target under an internally consistent service plan computed from the *current*
feasible region only:

    e  = baseline entry measurement point for the target
    e2 = baseline follow-up measurement point measured from e (same region)
    z  = safe clear point of the same region reached from e2
    ΔT = [||p-e|| + ||e-e2|| + ||e2-z|| + ||z-S_next|| - ||p-S_next||]/5 + T_nonmove

Insert the best target only when ΔT <= -hysteresis_s, at most one insertion per
station window, and never for a target that already reached the station-delay cap.
Coverage obligations, the 16-channel closure and every certificate stay untouched.
"""
import numpy as np

from active_localization import ActiveLocalizationSolver
from solver import safe_clear_point

import joint_search as joint_module
import omni_search as omni_module

__all__ = ['InsertionMixin', 'joint_module', 'omni_module']


class InsertionMixin:
    search_module = None

    def _setup_insertion(self, insert=True, hysteresis_s=8., max_delay_stations=3,
                         max_insertions_per_window=1, opportunistic_same_stop=False):
        self.insertion_enabled = bool(insert)
        self.insertion_hysteresis = float(hysteresis_s)
        self.insertion_max_delay = int(max_delay_stations)
        self.insertion_window_cap = int(max_insertions_per_window)
        self.insertion_opportunistic = bool(opportunistic_same_stop)
        self.diagnostics.update(insertion_evals=0, insertion_accepted=0,
                                insertion_predicted_savings=0., insertion_skipped_delay=0,
                                insertion_best_dt=0.)

    # ---- service plan --------------------------------------------------
    def _service_plan(self, c):
        """Entry point e, predicted exit z and own non-move cost of serving c now.

        The plan follows the procedure the solver would actually run:
          radius <= 19.99        -> certified clear from the current position
          radius <= probe_radius -> small-region optical probe at the posterior
                                    centre (e = z = centre, one optical attempt)
          otherwise              -> baseline entry measurement, exit at the
                                    posterior centre (prediction, not a certificate)
        """
        poly, center, radius = self.region(c)
        probe = getattr(self, 'probe_radius', 0.)
        if radius > 19.99 and radius <= probe:
            ctr = np.asarray(center, float)
            return ctr, ctr, 5.
        if radius <= 19.99:
            z = np.asarray(safe_clear_point(self.pos, center, radius), float)
            return z, z, 5.
        first = ActiveLocalizationSolver.directional_options(self, c, poly, center, radius)
        e = np.asarray(first[0], float) if first else np.asarray(center, float)
        return e, np.asarray(center, float), 15.

    def _insertion_choice(self, points, order):
        """Classical insertion saving for the best known target, or None.

        ΔT = [||p-e|| + ||z-S1|| + ||S1-S2||] - [||p-S1|| + ||S1-e|| + ||z-S2||] (÷5)
             + own non-move cost of the inserted service
        with S1 the router's first node (coverage station) and S2 the second node of
        the baseline order (falling back to z, which is the most favourable later
        plan and therefore biases the test against insertion).
        """
        n_targets = len(self.deferred)
        if n_targets == 0 or not order or len(order) < 1:
            return None
        first = int(order[0])
        if first < n_targets:
            return None                     # router already chose a target
        s1 = np.asarray(points[first], float)
        if len(order) > 1:
            s2 = np.asarray(points[int(order[1])], float)
        else:
            s2 = None
        before = float(np.linalg.norm(self.pos - s1)) / 5
        best, best_dt = None, 0.
        for slot, c in enumerate(list(self.deferred)):
            if self.deferred[c] >= self.insertion_max_delay:
                self.diagnostics['insertion_skipped_delay'] += 1
                continue
            e, z, nonmove = self._service_plan(c)
            later_exit = z if s2 is None else s2
            inserted = (float(np.linalg.norm(self.pos - e)) + float(np.linalg.norm(z - s1))
                        + (0. if s2 is None else float(np.linalg.norm(s1 - s2)))) / 5
            later = before + float(np.linalg.norm(s1 - e)) / 5 + float(np.linalg.norm(z - later_exit)) / 5
            dt = inserted - later + nonmove
            self.diagnostics['insertion_evals'] += 1
            self.diagnostics['insertion_best_dt'] = min(self.diagnostics.get('insertion_best_dt', 0.), dt)
            if dt < best_dt:
                best, best_dt = slot, dt
        if best is None or best_dt > -self.insertion_hysteresis:
            return None
        self.diagnostics['insertion_accepted'] += 1
        self.diagnostics['insertion_predicted_savings'] += -best_dt
        return best

    def run(self):
        if not self.insertion_enabled:
            return super().run()
        module = self.search_module
        original = module.search_route
        window = {'used': 0}

        def patched(points, start):
            order = original(points, start)
            if window['used'] >= self.insertion_window_cap:
                return order
            pick = self._insertion_choice(points, order)
            if pick is None:
                return order
            window['used'] += 1
            rest = [i for i in order if i != pick]
            return [pick] + rest

        module.search_route = patched
        try:
            return super().run()
        finally:
            module.search_route = original

