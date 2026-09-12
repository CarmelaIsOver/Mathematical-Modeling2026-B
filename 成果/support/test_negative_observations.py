"""Q3 negative-observation half-plane: geometry, integration and completeness."""
import unittest

import numpy as np

from negative_observations import apply_negative_halfplanes
from backend import LocalBackend
from audit import AuditPort
from omni_search import OmniSearchSolver


class HalfPlaneGeometryTests(unittest.TestCase):
    def test_received_not_received_pair_keeps_near_half_plane(self):
        # Received at p=(1000,0), not received at q=(-1000,0): every retained
        # position must be strictly closer to p, so x<0 is impossible.
        poly = np.array([[-500., -500.], [500., -500.], [500., 500.], [-500., 500.]])
        out, used = apply_negative_halfplanes(
            poly, [(np.array([1000., 0.]), 0.)], [np.array([-1000., 0.])])
        self.assertEqual(used, 1)
        self.assertTrue(len(out))
        self.assertTrue(np.all(out[:, 0] >= -1e-6))

    def test_identical_positions_add_no_constraint(self):
        poly = np.array([[0., 0.], [10., 0.], [10., 10.], [0., 10.]])
        out, used = apply_negative_halfplanes(
            poly, [(np.zeros(2), 0.)], [np.zeros(2)])
        self.assertEqual(used, 0)
        self.assertEqual(len(out), len(poly))

    def test_clip_can_empty_and_reports_for_caller_fallback(self):
        # Outer polygon already lies beyond the bisector: the intersection is
        # empty and the caller must restore the outer bound.
        poly = np.array([[2., 0.], [3., 0.], [3., 1.], [2., 1.]])
        out, used = apply_negative_halfplanes(
            poly, [(np.zeros(2), 0.)], [np.array([1., 0.])])
        self.assertEqual(used, 1)
        self.assertEqual(len(out), 0)


class NegativeIntegrationTests(unittest.TestCase):
    def test_default_arm_is_the_untouched_joint_scheduler(self):
        solver = OmniSearchSolver(None, 3)
        self.assertFalse(solver.use_negatives)
        self.assertFalse(solver.certify_on_tight)
        self.assertEqual(solver.negatives[1], [])

    def test_negatives_still_clear_every_source(self):
        for seed in (990025, 990000):
            backend = LocalBackend(seed, 3)
            port = AuditPort(backend)
            result = OmniSearchSolver(port, 3, negative_observations=True).run()
            self.assertEqual(result['cleared'], len(backend.sources))
            self.assertTrue(port.exited)
            self.assertGreater(result['negative_observations'], 0)
            self.assertGreater(result['negative_constraints'], 0)

    def test_region_cache_keys_on_both_observation_counts(self):
        solver = OmniSearchSolver(None, 3)
        solver.use_negatives = True
        c = 5
        solver.obs[c].append((np.array([500., 0.]), 0.))
        _, _, before = solver.tight_region(c)
        self.assertEqual(solver.cache[c][0], (1, 0))
        solver.negatives[c].append(np.array([-500., 0.]))
        _, _, after = solver.tight_region(c)
        self.assertEqual(solver.cache[c][0], (1, 1))
        self.assertLessEqual(after, before + 1e-9)


if __name__ == '__main__':
    unittest.main()
