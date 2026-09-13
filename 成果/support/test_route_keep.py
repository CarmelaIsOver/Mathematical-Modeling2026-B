"""Q3 route-keeping invariants: stable ids, completion keeps order, new task replans."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / 'research' / 'iterative_speed'))

from route_keep import plan_reuse  # noqa: E402
from variants import VARIANTS  # noqa: E402


class PlanReuseTests(unittest.TestCase):
    def test_initial_plan_is_identity(self):
        order, reason = plan_reuse([], ['A', 'B', 'C'])
        self.assertEqual(reason, 'initial')
        self.assertEqual(order, [0, 1, 2])

    def test_completed_task_only_removes_itself(self):
        """Saved order [A,B,C]; B completed -> [A,C] with the relative order kept."""
        order, reason = plan_reuse(['A', 'B', 'C'], ['A', 'C'])
        self.assertEqual(reason, 'reused')
        self.assertEqual(order, [0, 1])

    def test_order_is_preserved_even_when_the_caller_reorders_points(self):
        """The kept order is the saved sequence, not the caller's array order."""
        order, reason = plan_reuse(['A', 'B', 'C'], ['C', 'A', 'B'])
        self.assertEqual(reason, 'reused')
        self.assertEqual([['C', 'A', 'B'][i] for i in order], ['A', 'B', 'C'])

    def test_overdue_target_forces_a_refresh(self):
        """A live target waiting >= max_defer_age must break the kept plan."""
        ages = {'A': 0, 'B': 5, 'C': 1}
        order, reason = plan_reuse(['A', 'B', 'C'], ['A', 'B', 'C'],
                                   defer_age=lambda tid: ages[tid], max_defer_age=3)
        self.assertEqual(reason, 'overdue')
        self.assertEqual(order, [0, 1, 2])

    def test_no_target_overdue_keeps_reusing(self):
        ages = {'A': 0, 'B': 2, 'C': 1}
        order, reason = plan_reuse(['A', 'B', 'C'], ['A', 'B', 'C'],
                                   defer_age=lambda tid: ages[tid], max_defer_age=3)
        self.assertEqual(reason, 'reused')

    def test_stations_never_trigger_overdue(self):
        order, reason = plan_reuse([('t', 5), ('s', 1, 0)], [('t', 5), ('s', 1, 0)],
                                   defer_age=lambda tid: -1, max_defer_age=1)
        self.assertEqual(reason, 'reused')

    def test_new_task_takes_priority_over_overdue(self):
        ages = {'A': 9}
        order, reason = plan_reuse(['A'], ['A', 'B'], defer_age=lambda tid: ages.get(tid, 0),
                                   max_defer_age=1)
        self.assertEqual(reason, 'new_task')

    def test_new_task_forces_a_replan(self):
        order, reason = plan_reuse(['A', 'B'], ['A', 'B', 'C'])
        self.assertEqual(reason, 'new_task')
        self.assertEqual(order, [0, 1, 2])

    def test_no_task_is_lost_or_duplicated(self):
        saved = ['A', 'B', 'C', 'D']
        for current in (['A', 'B', 'C', 'D'], ['B', 'D'], ['D'], ['C', 'D'], ['A', 'C']):
            order, reason = plan_reuse(saved, current)
            self.assertEqual(sorted(order), list(range(len(current))),
                             f'order must be a permutation for {current}')
            self.assertEqual(len(set(order)), len(order))

    def test_duplicate_ids_are_refused(self):
        order, reason = plan_reuse(['A', 'B'], ['A', 'A', 'B'])
        self.assertEqual(reason, 'invalid')

    def test_empty_current(self):
        self.assertEqual(plan_reuse(['A'], []), ([], 'invalid'))


class StationIdentityTests(unittest.TestCase):
    def test_station_ids_are_stable_across_calls_and_change_with_the_layout(self):
        cls, kwargs = VARIANTS[3]['q3_keep']
        solver = cls(None, 3, **kwargs)
        solver.deferred = {}
        solver.pending_stations = [0, 1, 2]
        before = solver._current_task_ids()
        self.assertEqual(before, solver._current_task_ids(), 'identical state -> identical ids')
        self.assertTrue(all(t[0] in ('t', 's') for t in before), 'ids must be typed')
        self.assertEqual(len(before), len(set(before)), 'ids must be unique')
        solver.stations = np.array([[0., 0.], [9999., 9999.], [5555., 5555.]])
        after = solver._current_task_ids()
        self.assertNotEqual([t[1] for t in before], [t[1] for t in after],
                            'a new station layout must bump the generation')
        self.assertEqual([t[2] for t in after], [0, 1, 2])

    def test_ids_use_channels_for_targets(self):
        cls, kwargs = VARIANTS[3]['q3_keep']
        solver = cls(None, 3, **kwargs)
        solver.deferred = {7: 1, 12: 2}
        solver.pending_stations = []
        self.assertEqual(solver._current_task_ids(), [('t', 7), ('t', 12)])


class IntegrationTests(unittest.TestCase):
    def test_run_keeps_the_route_and_finishes_every_obligation(self):
        from audit import AuditPort
        from backend import LocalBackend
        cls, kwargs = VARIANTS[3]['q3_keep']
        backend = LocalBackend(3499000, 3)
        port = AuditPort(backend)
        solver = cls(port, 3, **kwargs)
        result = solver.run()
        self.assertEqual(result['cleared'], len(backend.sources))
        self.assertEqual(sorted(solver.visited), list(range(len(solver.stations))),
                         'every coverage site must still be visited exactly once')
        self.assertGreater(result.get('route_reuses', 0), 0,
                           'a real completion must reuse the plan at least once')
        self.assertGreater(result.get('route_replans', 0), 0)
        # the overdue counter must be live: with an aggressive age bound the refresh
        # path has to fire in a normal scene
        backend2 = LocalBackend(3499000, 3)
        port2 = AuditPort(backend2)
        solver2 = cls(port2, 3, **dict(kwargs, max_defer_age=1))
        result2 = solver2.run()
        self.assertEqual(result2['cleared'], len(backend2.sources))
        self.assertGreater(result2.get('route_replan_overdue', 0), 0,
                           'the overdue refresh must be reachable, not dead code')
        self.assertLessEqual(result.get('plan_reversals', 0), result.get('route_reuses', 0))


if __name__ == '__main__':
    unittest.main()
