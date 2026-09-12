"""Q4 discovery closure: the 16-source upper bound ends the search obligation."""
import unittest

import numpy as np

from backend import LocalBackend
from audit import AuditPort
from joint_search import JointSearchSolver

SIXTEEN = 1900011   # 16 sources; natural closure on the default radial layout
FEWER = 1800011     # 11 sources; the upper bound is never reached


class DiscoveryClosureTests(unittest.TestCase):
    def test_default_layout_closes_discovery_at_sixteen(self):
        backend = LocalBackend(SIXTEEN, 4)
        port = AuditPort(backend)
        solver = JointSearchSolver(port, 4)
        result = solver.run()
        self.assertEqual(len(backend.sources), 16)
        self.assertEqual(result['cleared'], 16)
        self.assertTrue(port.exited)
        self.assertEqual(result['discovery_closed'], 1)
        self.assertGreater(result['coverage_sites_cancelled'], 0)
        self.assertLess(result['stations_visited'], len(solver.stations))
        self.assertFalse(any(c not in solver.cleared for c in solver.deferred))

    def test_fewer_than_sixteen_keeps_full_discovery(self):
        backend = LocalBackend(FEWER, 4)
        port = AuditPort(backend)
        solver = JointSearchSolver(port, 4)
        result = solver.run()
        self.assertEqual(result['cleared'], len(backend.sources))
        self.assertEqual(result['discovery_closed'], 0)
        self.assertEqual(result['coverage_sites_cancelled'], 0)
        self.assertEqual(result['stations_visited'], len(solver.stations))
        # Every still-unknown channel is measured at every visited site.
        for c in set(range(1, 21)) - set(backend.sources):
            for p in solver.stations:
                self.assertTrue(any(np.array_equal(p, q) for q in solver.measured[c]))

    def test_closure_can_be_disabled_for_ab_comparison(self):
        backend = LocalBackend(SIXTEEN, 4)
        port = AuditPort(backend)
        solver = JointSearchSolver(port, 4, close_discovery_on_upper_bound=False)
        result = solver.run()
        self.assertEqual(result['cleared'], 16)
        self.assertEqual(result['discovery_closed'], 0)
        self.assertEqual(result['coverage_sites_cancelled'], 0)
        self.assertEqual(result['stations_visited'], len(solver.stations))


if __name__ == '__main__':
    unittest.main()
