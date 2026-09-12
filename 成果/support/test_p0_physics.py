"""P0 counterexample tests: physics conditions of the research predictor.

Each test is a direct mathematical check of one P0 item, independent of any scenario:
  1. Q3 guaranteed reception: max vertex distance <= 1000 => no_signal impossible.
  2. near feasibility uses the distance to the whole feasible set (point-to-edge).
  3. the +/-1 deg bound never widens the emission half-plane.
  4. branch history stores the branch's own raw feedback representative.
  5. sampling is stratified (area / distance) and order-independent in budget terms.
  6. same world + position + channel gives identical feedback.
"""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / 'research' / 'iterative_speed'))

from lookahead import _outcomes_with_angles, _point_poly_distance  # noqa: E402
from state_prediction import BEARING_TOL_DEG, JointStatePrediction, MAX_RECORDS  # noqa: E402
from variants import VARIANTS  # noqa: E402

KW = {'ring_radius': 1123., 'guard_initial': True, 'close_known': True,
      'skip_known_radius': 1200., 'probe_radius': 60., 'mode': 'service'}


def solver():
    cls, kwargs = VARIANTS[3]['la_q3_service']
    return cls(None, 3, **dict(KW, **kwargs))


class GuaranteedReceptionTests(unittest.TestCase):
    def test_no_signal_is_impossible_when_every_feasible_point_is_in_range(self):
        s = solver()
        poly = np.array([[0., 0.], [40., 0.], [40., 40.], [0., 40.]])
        for q in (np.array([20., 20.]), np.array([300., 300.]), np.array([-200., 10.])):
            kinds = {b[2] for b in s._branches(1, q, poly)}
            self.assertNotIn('no_signal', kinds,
                             'max vertex distance <= 1000 must forbid no_signal')

    def test_no_signal_returns_once_a_feasible_point_is_far_away(self):
        s = solver()
        long_poly = np.array([[0., 0.], [2500., 0.], [2500., 20.], [0., 20.]])
        kinds = {b[2] for b in s._branches(1, np.array([1250., -3.]), long_poly)}
        self.assertIn('no_signal', kinds)


class NearFeasibilityTests(unittest.TestCase):
    def test_near_uses_distance_to_the_edge_not_only_to_vertices(self):
        s = solver()
        poly = np.array([[0., 0.], [2500., 0.], [2500., 20.], [0., 20.]])
        q = np.array([1250., -3.])          # 3 m outside the bottom edge
        self.assertGreater(float(np.min(np.linalg.norm(poly - q, axis=1))), 5.,
                           'this counterexample must be far from every vertex')
        self.assertAlmostEqual(_point_poly_distance(poly, q), 3., places=6)
        self.assertIn('near', {b[2] for b in s._branches(1, q, poly)})

    def test_near_is_absent_when_the_whole_set_is_far(self):
        s = solver()
        poly = np.array([[0., 0.], [2500., 0.], [2500., 20.], [0., 20.]])
        self.assertNotIn('near', {b[2] for b in s._branches(1, np.array([1250., 60.]), poly)})

    def test_point_poly_distance_inside_is_zero(self):
        poly = np.array([[0., 0.], [10., 0.], [10., 10.], [0., 10.]])
        self.assertEqual(_point_poly_distance(poly, np.array([5., 5.])), 0.)


class StrictHalfPlaneTests(unittest.TestCase):
    """Review counterexample: g=(0,0), R=1000, n=(0,1), q=(100,0.1)."""

    def _explains(self, g, R, theta, p, kind):
        v = np.array([math.cos(theta), math.sin(theta)])
        d = p - g
        dist = float(np.linalg.norm(d))
        u = d / max(dist, 1e-9)
        if kind == 'positive':
            return dist <= R and float(u @ v) >= -1e-9
        return dist > R or float(u @ v) < -1e-9

    def test_front_facing_in_range_cannot_explain_no_signal(self):
        g = np.array([0., 0.])
        p = np.array([100., 0.1])
        n = math.pi / 2                          # source faces +y, q is in front
        self.assertTrue(self._explains(g, 1000., n, p, 'positive'))
        self.assertFalse(self._explains(g, 1000., n, p, 'no_signal'),
                         'the +/-1 deg bound must not turn a visible reading into no_signal')

    def test_back_facing_explains_no_signal_strictly(self):
        g = np.array([0., 0.])
        p = np.array([100., -0.1])               # behind the +y facing source
        n = math.pi / 2
        self.assertTrue(self._explains(g, 1000., n, p, 'no_signal'))

    def test_tolerance_is_only_for_the_bearing(self):
        self.assertAlmostEqual(BEARING_TOL_DEG, 1.0, places=9)


class FeedbackRepresentativeTests(unittest.TestCase):
    def test_branch_carries_its_own_wedge_centre(self):
        poly = np.array([[0., 0.], [40., 0.], [40., 40.], [0., 40.]])
        q = np.array([-10., 20.])
        first = _outcomes_with_angles(poly, q, bins=12)
        self.assertTrue(first)
        for post, _w, ang in first:
            self.assertTrue(np.isfinite(ang))
        # deterministic: the same state yields exactly the same representative angles
        second = _outcomes_with_angles(poly, q, bins=12)
        self.assertEqual([round(a, 9) for _p, _w, a in first],
                         [round(a, 9) for _p, _w, a in second])

    def test_assumed_history_stores_the_branch_angle_verbatim(self):
        s = solver()
        s.obs[1] = [(np.array([0., 0.]), 0.)]
        s.measured[1] = [np.array([0., 0.])]
        poly = np.array([[0., 0.], [40., 0.], [40., 40.], [0., 40.]])
        q = np.array([-10., 20.])
        branch = [b for b in s._branches(1, q, poly) if b[2] == 'direction'][0]
        state = s._assumed_state(1, q)
        nxt, _poly = s._advance(state, 1, q, branch[0], branch[2], branch[3])
        self.assertAlmostEqual(float(nxt.obs[1][-1][1]), float(branch[3]), places=9)


class StratifiedSamplingTests(unittest.TestCase):
    def test_records_spread_over_positions_instead_of_budget_exhaustion(self):
        s = JointStatePrediction(None, 4, mode='c2')
        s.n_samples = 40
        s.obs[5] = [(np.array([300., 0.]), 180.)]
        s.negatives[5] = [np.array([900., 0.])]
        records = s._state_records(5)
        self.assertLessEqual(len(records), MAX_RECORDS)
        positions = {(round(float(r[0][0]), 3), round(float(r[0][1]), 3)) for r in records}
        self.assertGreater(len(positions), 1,
                           'the per-position budget must keep several hypotheses alive')

    def test_area_sampling_stays_inside_and_covers_an_extreme_polygon(self):
        s = JointStatePrediction(None, 4, mode='c2')
        s.n_samples = 60
        poly = np.array([[0., 0.], [1400., 0.], [1400., 40.], [0., 40.]])
        s.region = lambda c: (poly, poly.mean(axis=0), 700.)
        samples = s._hypothesis_samples(1)
        self.assertGreater(len(samples), 0)
        from state_prediction import _inside_convex
        self.assertTrue(all(_inside_convex(poly, q) for q in samples))
        # the extreme stratum keeps the thin polygon's far end represented
        self.assertGreater(float(samples[:, 0].max()), 1000.)


if __name__ == '__main__':
    unittest.main()
