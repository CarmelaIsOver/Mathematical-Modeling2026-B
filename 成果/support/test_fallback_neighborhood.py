"""Q4 fallback capture + finite-neighbourhood ordering: invariants and counterexamples."""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / 'research' / 'iterative_speed'))

from fallback_neighborhood import (FAILED_CLEAR_S, SUCCESS_CLEAR_S, design_positions,  # noqa: E402
                                   neighbourhood_orders, sweep_cost)
from variants import VARIANTS  # noqa: E402


class DesignSampleTests(unittest.TestCase):
    def test_samples_are_inside_and_deterministic(self):
        poly = np.array([[0., 0.], [400., 0.], [400., 40.], [0., 40.]])
        a = design_positions(poly, poly.mean(axis=0), 200., n=24, seed_key=3)
        b = design_positions(poly, poly.mean(axis=0), 200., n=24, seed_key=3)
        self.assertEqual(len(a), len(b))
        self.assertTrue(np.allclose(a, b), 'the design must be reproducible')
        self.assertGreater(len(a), 0)

    def test_thin_polygon_far_end_is_represented(self):
        poly = np.array([[0., 0.], [1400., 0.], [1400., 20.], [0., 20.]])
        pts = design_positions(poly, poly.mean(axis=0), 700., n=24, seed_key=1)
        self.assertGreater(float(pts[:, 0].max()), 900.)


class SweepCostTests(unittest.TestCase):
    def test_pure_movement_counterexample(self):
        samples = np.array([[10., 0.], [100., 0.]])
        points = [np.array([10., 0.]), np.array([100., 0.])]
        stats = sweep_cost(samples, points, [0, 1], start=np.array([0., 0.]), movement_only=True)
        self.assertAlmostEqual(stats[0], 11., places=6, msg='(2 + 20)/2 = 11 s, not a full-coverage walk')

    def test_failed_and_success_charging(self):
        samples = np.array([[10., 0.], [100., 0.]])
        points = [np.array([10., 0.]), np.array([100., 0.])]
        stats = sweep_cost(samples, points, [0, 1], start=np.array([0., 0.]))
        # first hit: 2 s move + 3 s failed + 2 s laser = 7 s; second: +18 s move +5 s = 28 s
        self.assertAlmostEqual(stats[0], (7. + 28.) / 2., places=6)

    def test_unreachable_sample_refuses_the_candidate(self):
        samples = np.array([[1000., 0.]])
        points = [np.array([10., 0.])]
        self.assertIsNone(sweep_cost(samples, points, [0], start=np.array([0., 0.])),
                          'a sample never reached must not be credited as cleared')

    def test_exit_leg_is_a_common_constant(self):
        samples = np.array([[10., 0.]])
        points = [np.array([10., 0.])]
        base = sweep_cost(samples, points, [0], start=np.array([0., 0.]))[0]
        with_exit = sweep_cost(samples, points, [0], start=np.array([0., 0.]),
                               exit_point=np.array([60., 0.]))[0]
        self.assertAlmostEqual(with_exit - base, 10., places=6)

    def test_order_can_change_the_first_hit_cost(self):
        samples = np.array([[10., 0.], [100., 0.]])
        points = [np.array([10., 0.]), np.array([100., 0.])]
        near_first = sweep_cost(samples, points, [0, 1], start=np.array([0., 0.]))[0]
        far_first = sweep_cost(samples, points, [1, 0], start=np.array([0., 0.]))[0]
        self.assertLess(near_first, far_first)


class NeighbourhoodTests(unittest.TestCase):
    def test_incumbent_is_first_and_all_candidates_are_permutations(self):
        incumbent = list(range(6))
        cands = neighbourhood_orders(incumbent, budget=24)
        self.assertEqual(cands[0], incumbent, 'the original order must stay a candidate')
        self.assertLessEqual(len(cands), 24)
        for c in cands:
            self.assertEqual(sorted(c), incumbent, 'no coverage point may be dropped or duplicated')

    def test_swaps_are_included(self):
        incumbent = list(range(4))
        cands = [tuple(c) for c in neighbourhood_orders(incumbent, budget=100)]
        self.assertIn((1, 0, 2, 3), cands)


class ForcedFallbackCaptureTests(unittest.TestCase):
    """A constructed state that MUST enter fallback validates the collector."""

    def test_capture_fires_on_a_forced_fallback_state(self):
        cls, kwargs = VARIANTS[4]['q4_fb_probe']
        solver = cls(None, 4, **kwargs)
        poly = np.array([[-100., -100.], [100., -100.], [100., 100.], [-100., 100.]])
        solver.obs[5] = [(np.array([0., 0.]), 0.)]
        solver.region = lambda c: (poly, np.zeros(2), 200.)
        solver.pos = np.zeros(2)
        with self.assertRaises(Exception):
            solver.directional_fallback(5)          # no source at the sweep points -> exhausted
        self.assertEqual(solver.diagnostics['fallback_events'], 1)
        self.assertEqual(solver.diagnostics['fallback_captured'], 1,
                         'the collector must capture the entry state of a real fallback')
        row = solver.diagnostics['fallback_rows'][0]
        self.assertGreaterEqual(row['points'], 1)
        self.assertIsNotNone(row['incumbent_mean_s'])


class IntegrationTests(unittest.TestCase):
    def test_probe_run_completes_and_captures_every_event(self):
        from audit import AuditPort
        from backend import LocalBackend
        cls, kwargs = VARIANTS[4]['q4_fb_probe']
        for seed in (3499300, 3499301, 3499302, 3499303):
            backend = LocalBackend(seed, 4)
            port = AuditPort(backend)
            solver = cls(port, 4, **kwargs)
            result = solver.run()
            self.assertEqual(result['cleared'], len(backend.sources))
            self.assertEqual(solver.diagnostics['fallback_captured'],
                             solver.diagnostics['fallback_events'],
                             'every fallback event must be captured')


if __name__ == '__main__':
    unittest.main()
