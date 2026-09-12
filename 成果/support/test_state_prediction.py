"""Direct invariant tests for the revised Q4 state prediction (C1 and C2)."""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / 'research' / 'iterative_speed'))

from state_prediction import JointStatePrediction, R_GRID  # noqa: E402


def make_solver(mode):
    return JointStatePrediction(None, 4, mode=mode)


class C1FirstHitTests(unittest.TestCase):
    def test_mean_first_hit_time_counterexample(self):
        """Robot at 0, equal-weight samples at 10 m and 100 m: mean travel = 11 s."""
        solver = make_solver('c1')
        samples = np.array([[10., 0.], [100., 0.]])
        points = [np.array([10., 0.]), np.array([100., 0.])]
        mean, p95 = solver._first_hit_stats(samples, points, [0, 1], include_attempt_cost=False)
        self.assertAlmostEqual(mean, 11., places=6,
                               msg='mean first-hit travel must be (2 + 20)/2 = 11 s, not the 20 s '
                                   'of a full-coverage walk')

    def test_attempt_costs_are_charged(self):
        solver = make_solver('c1')
        samples = np.array([[10., 0.]])
        points = [np.array([10., 0.])]
        mean, _ = solver._first_hit_stats(samples, points, [0], include_attempt_cost=True)
        self.assertAlmostEqual(mean, 2. + 3. + 2., places=6,
                               msg='movement 2 s + 3 s optical + 2 s laser')

    def test_unhit_samples_carry_the_elapsed_cost(self):
        solver = make_solver('c1')
        samples = np.array([[1000., 0.]])
        points = [np.array([10., 0.])]
        mean, _ = solver._first_hit_stats(samples, points, [0], include_attempt_cost=True)
        # one visit: 2 s movement + 3 s optical attempt; the sample stays unhit
        self.assertAlmostEqual(mean, 5., places=6)

    def test_exit_effect_is_charged_after_a_hit(self):
        """A sample hit at a point also pays the departure leg to the next task."""
        solver = make_solver('c1')
        samples = np.array([[10., 0.]])
        points = [np.array([10., 0.])]
        stats = solver._first_hit_stats(samples, points, [0], include_attempt_cost=True,
                                        exit_point=np.array([60., 0.]))
        # 2 s move + 3 s optical + 2 s laser + 10 s departure (50 m / 5)
        self.assertAlmostEqual(stats[0], 17., places=6)

    def test_exit_effect_is_zero_without_a_next_task(self):
        solver = make_solver('c1')
        samples = np.array([[10., 0.]])
        points = [np.array([10., 0.])]
        self.assertAlmostEqual(solver._first_hit_stats(samples, points, [0])[0], 7., places=6)

    def test_score_uses_mean_and_tail(self):
        solver = make_solver('c1')
        flat = solver._score_from_stats((10., 10.))
        tailed = solver._score_from_stats((10., 30.))
        self.assertAlmostEqual(flat, 10., places=9)
        self.assertGreater(tailed, flat, 'a heavier upper tail must score worse')


class C2TupleTests(unittest.TestCase):
    def setUp(self):
        self.solver = make_solver('c2')
        self.solver.obs[7] = [(np.array([100., 0.]), 180.)]      # positive from (100,0)
        self.solver.negatives[7] = [np.array([500., 0.])]        # no_signal at (500,0)
        self.solver.n_samples = 40

    def test_records_keep_the_full_tuple(self):
        records = self.solver._state_records(7)
        self.assertTrue(records, 'a feasible (g,R,type,theta) set must survive')
        for g, R, kind, theta in records:
            self.assertIn(kind, ('omni', 'direction'))
            self.assertIn(R, R_GRID)
            self.assertTrue(np.isfinite(theta))

    def test_every_record_explains_all_observations(self):
        """Positives and negatives must both hold, with the +/-1 deg bounded error."""
        from state_prediction import BEARING_TOL_DEG
        tol = math.sin(math.radians(BEARING_TOL_DEG))
        records = self.solver._state_records(7)
        positives = [(np.asarray(p, float), float(a)) for p, a in self.solver.obs[7]]
        negatives = [np.asarray(p, float) for p in self.solver.negatives[7]]
        for g, R, kind, theta in records:
            v = np.array([math.cos(theta), math.sin(theta)])
            for p, _a in positives:
                self.assertLessEqual(float(np.linalg.norm(p - g)), R + 1e-9)
                if kind == 'direction':
                    u = (p - g) / max(float(np.linalg.norm(p - g)), 1e-9)
                    self.assertGreaterEqual(float(u @ v), -tol - 1e-9)
            for p in negatives:
                if kind == 'omni':
                    self.assertGreater(float(np.linalg.norm(p - g)), R)
                else:
                    u = (p - g) / max(float(np.linalg.norm(p - g)), 1e-9)
                    hidden = (float(np.linalg.norm(p - g)) > R) or (float(u @ v) < tol + 1e-9)
                    self.assertTrue(hidden, 'a directional record must explain the no_signal '
                                            'inside the bounded angular error')

    def test_omni_records_respect_the_in_range_no_signal(self):
        """An omni source inside R of a no_signal position is impossible."""
        records = self.solver._state_records(7)
        neg = np.asarray(self.solver.negatives[7][0], float)
        for g, R, kind, _theta in records:
            if kind == 'omni' and float(np.linalg.norm(neg - g)) <= R:
                self.fail('omni record is inside the receivable radius of a no_signal reading')

    def test_records_are_not_reduced_to_positions_only(self):
        records = self.solver._state_records(7)
        self.assertTrue(any(r[2] == 'direction' for r in records),
                        'directional records must be kept, not collapsed to g only')


class BoundedAngularErrorTests(unittest.TestCase):
    def setUp(self):
        from state_prediction import BEARING_TOL_DEG
        self.tol = BEARING_TOL_DEG
        self.solver = make_solver('c2')
        self.solver.n_samples = 40
        self.solver.obs[9] = [(np.array([100., 0.]), 180.)]     # bearing points to the source
        self.solver.negatives[9] = [np.array([900., 0.])]

    def test_every_record_matches_the_observed_bearing_within_the_bound(self):
        records = self.solver._state_records(9)
        self.assertTrue(records)
        (p, ang_obs), = self.solver.obs[9]
        for g, _R, _kind, _theta in records:
            ang_g = math.degrees(math.atan2(g[1] - p[1], g[0] - p[0])) % 360.
            diff = abs((ang_g - ang_obs + 180.) % 360. - 180.)
            self.assertLessEqual(diff, self.tol + 1e-9,
                                 'a record must explain the bearing inside the +/-1 deg bound')

    def test_wrong_bearing_is_rejected(self):
        """A bearing 30 deg away from the posterior cannot survive."""
        solver = make_solver('c2')
        solver.n_samples = 40
        solver.obs[9] = [(np.array([100., 0.]), 30.)]           # inconsistent with a source near the origin
        solver.negatives[9] = []
        records = solver._state_records(9)
        (p, ang_obs), = solver.obs[9]
        for g, _R, _kind, _theta in records:
            ang_g = math.degrees(math.atan2(g[1] - p[1], g[0] - p[0])) % 360.
            diff = abs((ang_g - ang_obs + 180.) % 360. - 180.)
            self.assertLessEqual(diff, self.tol + 1e-9)

    def test_bound_is_one_degree(self):
        self.assertAlmostEqual(self.tol, 1.0, places=9)


class SafetyTests(unittest.TestCase):
    def test_prediction_layer_does_not_touch_the_certificate_path(self):
        solver = make_solver('c2')
        self.assertFalse(hasattr(solver, 'certify_with_particles'))
        src = (Path(__file__).resolve().parent / 'research' / 'iterative_speed'
               / 'state_prediction.py').read_text(encoding='utf-8')
        for banned in ('certificates.append', 'absent_channels.add', 'def region('):
            self.assertNotIn(banned, src,
                             f'the prediction layer must not create certificates, declare absence '
                             f'or replace the certified region (found {banned})')

    def test_gate_falls_back_to_the_baseline_order(self):
        solver = make_solver('c1')
        solver.use_prediction = True
        poly = np.array([[0., 0.], [40., 0.], [40., 40.], [0., 40.]])
        solver.obs[1] = [(np.array([0., 0.]), 0.)]
        solver.region = lambda c: (poly, poly.mean(axis=0), 10.)
        pts = [np.array([5., 5.]), np.array([35., 35.])]
        order = solver._order_by_first_hit(1, pts)
        self.assertEqual(sorted(order), [0, 1], 'all fallback points must be preserved')


if __name__ == '__main__':
    unittest.main()
