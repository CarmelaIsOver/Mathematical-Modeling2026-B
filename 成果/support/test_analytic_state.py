"""N6 tests: analytic R/theta state (existence, intervals, strictness)."""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / 'research' / 'iterative_speed'))

from analytic_state import R_MAX, analyse_position  # noqa: E402


def state(g, pos, neg):
    return analyse_position(np.asarray(g, float), pos, neg)


class ExistenceTests(unittest.TestCase):
    def test_omni_feasible_while_directional_is_not(self):
        """Two opposite positives admit no single heading but are fine for an omni source."""
        s = state([0., 0.], [(np.array([100., 0.]), 0.), (np.array([-100., 0.]), 180.)], [])
        self.assertTrue(s.feasible)
        self.assertEqual(s.kind, 'omni', 'no heading can face both directions')

    def test_no_solution(self):
        s = state([0., 0.], [(np.array([100., 0.]), 0.)], [np.array([50., 0.])])
        # the negative is inside L and exactly in front: strictly back-facing is impossible
        self.assertFalse(s.feasible)

    def test_omni_only_when_a_close_negative_exists(self):
        s = state([0., 0.], [], [np.array([500., 0.])])
        self.assertEqual(s.kind, 'directional', 'a 500 m negative forbids every omni R>=1000')
        self.assertTrue(s.feasible)

    def test_L_over_1500_is_infeasible(self):
        s = state([0., 0.], [(np.array([1600., 0.]), 0.)], [])
        self.assertFalse(s.feasible)


class IntervalTests(unittest.TestCase):
    def test_narrow_directional_interval(self):
        pos = [(np.array([100., 0.]), 0.), (np.array([-100., 10.]), 180.)]
        s = state([0., 0.], pos, [])
        self.assertTrue(s.feasible)
        self.assertEqual(s.kind, 'directional')
        width = sum(hi - lo for lo, hi in s.theta_intervals)
        self.assertLess(width, math.pi)
        reps = s.theta_representatives()
        self.assertTrue(reps)
        for th in reps:
            n = np.array([math.cos(th), math.sin(th)])
            for p, _a in pos:
                self.assertGreaterEqual(float(n @ (p - s.g)), -1e-9)

    def test_wrapping_interval_representatives_satisfy_constraints(self):
        pos = [(np.array([100., 0.]), 0.), (np.array([0., 100.]), 90.)]
        s = state([0., 0.], pos, [])
        for lo, hi in s.theta_intervals:
            self.assertLessEqual(lo, hi, 'intervals must be non-wrapping slices')
        for th in s.theta_representatives():
            n = np.array([math.cos(th), math.sin(th)])
            for p, _a in pos:
                self.assertGreaterEqual(float(n @ (p - s.g)), -1e-9)

    def test_same_position_contradictory_feedback(self):
        p = np.array([100., 0.])
        s = state([0., 0.], [(p, 0.)], [p])
        self.assertFalse(s.feasible)


class RadiusTests(unittest.TestCase):
    def test_radius_interval_is_not_pinned_to_L(self):
        s = state([0., 0.], [(np.array([200., 0.]), 0.)], [])
        lo, hi, open_hi = s.radius_interval(0.)
        self.assertAlmostEqual(lo, 1000., places=6)
        self.assertAlmostEqual(hi, R_MAX, places=6)
        self.assertFalse(open_hi)

    def test_front_facing_negative_gives_a_strict_upper_bound(self):
        g = np.array([0., 0.])
        p = np.array([200., 0.])
        q = np.array([1200., 0.])           # beyond L=1000 and in front of heading 0
        s = state(g, [(p, 0.)], [q])
        self.assertTrue(s.feasible)
        self.assertEqual(s.kind, 'directional')
        lo, hi, open_hi = s.radius_interval(0.)
        self.assertTrue(open_hi, 'front-facing negative binds R strictly')
        self.assertAlmostEqual(hi, 1200., places=6)
        self.assertTrue(s.radius_ok(0., 1100.))
        self.assertFalse(s.radius_ok(0., 1200.), 'R == distance is excluded')

    def test_back_facing_negative_does_not_bound_the_radius(self):
        g = np.array([0., 0.])
        p = np.array([200., 0.])
        q = np.array([-1200., 0.])          # beyond L and behind heading 0
        s = state(g, [(p, 0.)], [q])
        self.assertTrue(s.feasible)
        lo, hi, open_hi = s.radius_interval(0.)
        self.assertFalse(open_hi)
        self.assertAlmostEqual(hi, R_MAX, places=6)


class NearRuleTests(unittest.TestCase):
    def test_near_is_a_feedback_priority_not_a_state_constraint(self):
        """The analytic state only constrains reception; near stays in the feedback rule."""
        src = (Path(__file__).resolve().parent / 'research' / 'iterative_speed'
               / 'world_rollout.py').read_text(encoding='utf-8')
        self.assertIn("if d <= 5.:", src)
        self.assertIn("return 'near', None", src)


if __name__ == '__main__':
    unittest.main()
