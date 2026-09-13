"""Q3: true remaining-route preservation with stable task identities.

The previous attempt keyed the saved plan on the *set* of remaining tasks, so any task
completion changed the key and forced a full re-plan (``route_reuses = 0``). This module
keeps the plan itself:

  * Tasks are identified by stable ids - ``('t', channel)`` for a known target and
    ``('s', layout_generation, station_index)`` for a coverage station. Array indices
    are never stored across calls and floating-point coordinates are never used for
    identity.
  * On every routing call the *current* ids (in the same order as the point array the
    caller built) are matched against the saved sequence:
      - a current id that was not in the saved plan  -> a new task appeared: re-plan
      - otherwise the saved relative order of the surviving ids is returned, so a
        completed task only removes itself.
  * Representative points are NOT frozen: the caller recomputes them from the latest
    public observations and the returned order is a permutation of the current points.

Only scheduling changes. Localization measurement points, clear/optical behaviour, the
coverage site set, certificates and the final coverage obligation are untouched.
"""
import numpy as np

from omni_search import OmniSearchSolver


def plan_reuse(saved_ids, current_ids, defer_age=None, max_defer_age=None):
    """Pure planner step: (ordered current indices, reason).

    ``saved_ids``     sequence of task ids in the previously planned order
    ``current_ids``   sequence of the task ids for the current call (same order as points)
    ``defer_age``     callable tid -> age in visited stations (None when not applicable)
    ``max_defer_age`` when set, a live target waiting >= this many visited stations forces
                      a refresh, so a kept plan can never starve a discovered target

    Returns the indices into ``current_ids`` in the order to execute, plus the reason:
    'initial' | 'new_task' | 'invalid' | 'overdue' | 'reused'.
    """
    if not current_ids:
        return [], 'invalid'
    if not saved_ids:
        return list(range(len(current_ids))), 'initial'
    if len(set(current_ids)) != len(current_ids):
        # duplicate ids cannot be ordered unambiguously: never guess
        return list(range(len(current_ids))), 'invalid'
    index_of = {}
    for i, tid in enumerate(current_ids):
        index_of[tid] = i
    for tid in current_ids:
        if tid not in saved_ids:
            return list(range(len(current_ids))), 'new_task'
    if max_defer_age is not None and defer_age is not None:
        for tid in current_ids:
            if int(defer_age(tid)) >= int(max_defer_age):
                return list(range(len(current_ids))), 'overdue'
    order = [index_of[tid] for tid in saved_ids if tid in index_of]
    if sorted(order) != list(range(len(current_ids))):
        return list(range(len(current_ids))), 'invalid'
    return order, 'reused'


class RouteKeepMixin:
    def _setup_route_keep(self, keep_plan=True, max_defer_age=None):
        self.route_keep = bool(keep_plan)
        # Revision r1: a kept plan must not starve discovered targets. When any known
        # uncleared channel has waited this many visited stations, the plan is
        # refreshed for that public reason only.
        self.route_keep_max_defer = None if max_defer_age is None else int(max_defer_age)
        self.diagnostics.update(route_reuses=0, route_replans=0,
                                route_replan_new_task=0, route_replan_initial=0,
                                plan_reversals=0, cleared_exit_distance_m=0.,
                                cleared_exit_count=0, route_keep_invalid=0,
                                route_replan_overdue=0)

    # ---- stable ids ------------------------------------------------------
    def _station_generation(self):
        """Monotone counter that changes when the station set is replaced."""
        sig = tuple((round(float(s[0]), 3), round(float(s[1]), 3)) for s in self.stations)
        if getattr(self, '_station_sig', None) != sig:
            self._station_sig = sig
            self._station_gen = getattr(self, '_station_gen', 0) + 1
        return self._station_gen

    def _current_task_ids(self):
        """Ids in exactly the order the run loop builds its point array."""
        ids = [('t', int(c)) for c in self.deferred]
        gen = self._station_generation()
        ids += [('s', gen, int(i)) for i in self.pending_stations]
        return ids

    # ---- exit accounting ------------------------------------------------
    def _live_nodes(self, exclude_channel):
        nodes = []
        for k in self.deferred:
            if k == exclude_channel:
                continue
            try:
                nodes.append(np.asarray(self.region(k)[1], float))
            except Exception:
                pass
        for i in self.pending_stations:
            nodes.append(np.asarray(self.stations[i], float))
        return nodes

    def _record_exit(self, channel):
        pts = getattr(self, '_rk_points', None)
        order = getattr(self, '_rk_order', None)
        if pts is None or order is None:
            return
        live = self._live_nodes(channel)
        if not live:
            return
        for idx in order:
            if idx >= len(pts):
                continue
            node = np.asarray(pts[idx], float)
            if any(float(np.linalg.norm(node - n)) < .5 for n in live):
                self.diagnostics['cleared_exit_distance_m'] += float(np.linalg.norm(node - self.pos))
                self.diagnostics['cleared_exit_count'] += 1
                return

    def certified_clear(self, c, poly, center, radius):
        super().certified_clear(c, poly, center, radius)
        self._record_exit(c)

    # ---- run -------------------------------------------------------------
    def run(self):
        import omni_search as module
        original = module.search_route
        state = {'ids': None}

        def patched(points, start):
            self._rk_points = points
            current = self._current_task_ids()
            age_now = len(self.visited)
            deferred_now = getattr(self, 'deferred', {}) or {}

            def _defer_age(tid):
                if not (isinstance(tid, tuple) and len(tid) == 2 and tid[0] == 't'):
                    return -1
                return age_now - int(deferred_now.get(tid[1], age_now))

            order, reason = plan_reuse(state['ids'], current, defer_age=_defer_age,
                                       max_defer_age=self.route_keep_max_defer) \
                if self.route_keep else (list(range(len(current))), 'initial')
            if reason == 'reused':
                fresh = list(original(points, start))
                if len(fresh) and len(order) and fresh[0] != order[0]:
                    self.diagnostics['plan_reversals'] += 1
                self.diagnostics['route_reuses'] += 1
            else:
                order = list(original(points, start))
                self.diagnostics['route_replans'] += 1
                if reason == 'overdue':
                    self.diagnostics['route_replan_overdue'] += 1
                elif reason == 'new_task':
                    self.diagnostics['route_replan_new_task'] += 1
                elif reason == 'initial':
                    self.diagnostics['route_replan_initial'] += 1
                else:
                    self.diagnostics['route_keep_invalid'] += 1
            state['ids'] = [current[i] for i in order]
            self._rk_order = list(order)
            return order

        module.search_route = patched
        try:
            return super().run()
        finally:
            module.search_route = original
