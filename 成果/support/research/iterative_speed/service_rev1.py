"""Revision r1 of the ported adaptive service (opt-in; teammate logic left pristine).

Measured tail mechanism (seed 3502044, 16 sources, +50.8%): partial advances make the
scheduler bounce between many known targets while the station tour is still running
(coverage movement 19005 m vs 2563 m for the atomic locator, localization 0 vs 10567 m,
29 service visits of which 13 returned without clearing anything). The first guard
attempt keyed on ``discovery_closed`` and never fired, because the shuttling happens
*early* (1-3 stations visited, 6-10 known targets).

Revision (public information only - no seed, truth, radius, direction or source count):
  * a visit that changes neither the positive observations nor the negative budget of
    the target is a no-progress visit; the target is then completed immediately with the
    local full locator in the same visit, so it can never be re-selected to bounce again;
  * a target may return to the scheduler at most ``max_returns`` times with progress;
    the next selection finishes it in place.
"""
from solver import Solver
from localization_service import LocalizationService


class LocalizationServiceRev1(LocalizationService):
    def __init__(self, controller, no_progress_limit=1, max_returns=2):
        super().__init__(controller)
        self.no_progress_limit = int(no_progress_limit)
        self.max_returns = int(max_returns)
        self._no_progress = {}
        self._returns = {}
        self.s.diagnostics.update(service_no_progress_forced=0, service_finished_in_place=0)

    def _mark(self, key):
        self.s.diagnostics[key] = self.s.diagnostics.get(key, 0) + 1

    def _public_progress_key(self, c):
        return (len(self.s.obs[c]), len(self.negatives.get(c, ())))

    def advance_directional(self, c):
        s = self.s
        if c in s.cleared:
            return
        if self._no_progress.get(c, 0) >= self.no_progress_limit \
                or self._returns.get(c, 0) >= self.max_returns:
            self._mark('service_finished_in_place')
            self._no_progress[c] = 0
            self._returns[c] = 0
            return Solver.locate(s, c)
        before = self._public_progress_key(c)
        super().advance_directional(c)
        if c in s.cleared:
            self._no_progress[c] = 0
            self._returns[c] = 0
            return
        if self._public_progress_key(c) == before:
            self._no_progress[c] = self._no_progress.get(c, 0) + 1
            self._mark('service_no_progress_forced')
            self._returns[c] = 0
            return Solver.locate(s, c)          # finish now, in place
        self._no_progress[c] = 0
        self._returns[c] = self._returns.get(c, 0) + 1
