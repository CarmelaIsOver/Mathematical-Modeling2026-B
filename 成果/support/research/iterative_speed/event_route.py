"""N3: event-triggered route keeping with a real exit node.

The production Q3 loop re-solves the joint open route at every decision
(``OmniSearchSolver.run`` calls the module-level ``search_route`` each iteration).
This module keeps the previously planned order and only re-plans when the TASK SET
changes - a real event: a new target discovered, a target cleared, a station
consumed, or discovery closed. A drifting region centre or a small position change
does not trigger a re-plan.

It also records exit consistency: the distance from each clear point to the next live
node of the *saved* route, and whether keeping the plan ever disagrees with what a
fresh re-plan would have chosen first (``plan_reversals``).

Coverage sites, measurement/clear rules and the 2-opt neighbourhood are untouched.
"""
import numpy as np

from omni_search import OmniSearchSolver


class EventRouteMixin:
    def _setup_event_route(self, keep_plan=True):
        self.event_keep_plan = bool(keep_plan)
        self.diagnostics.update(event_replans=0, route_reuses=0, plan_reversals=0,
                                cleared_exit_distance_m=0., cleared_exit_count=0)

    def _route_key(self):
        return (tuple(sorted(self.deferred)), tuple(self.pending_stations))

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
        pts = getattr(self, '_event_points', None)
        order = getattr(self, '_event_order', None)
        if pts is None or not order:
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

    def run(self):
        import omni_search as module
        original = module.search_route
        state = {'key': None, 'order': None}

        def patched(points, start):
            self._event_points = points
            key = self._route_key()
            if self.event_keep_plan and key == state['key'] and state['order'] is not None:
                fresh = original(points, start)
                if len(fresh) and len(state['order']) and fresh[0] != state['order'][0]:
                    self.diagnostics['plan_reversals'] += 1
                self.diagnostics['route_reuses'] += 1
                self._event_order = list(state['order'])
                return list(state['order'])
            order = list(original(points, start))
            state['key'], state['order'] = key, order
            self.diagnostics['event_replans'] += 1
            self._event_order = list(order)
            return order

        module.search_route = patched
        try:
            return super().run()
        finally:
            module.search_route = original
