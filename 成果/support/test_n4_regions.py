"""N4 counterexample tests + same-state comparison helpers."""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / 'research' / 'iterative_speed'))

from n4_regions import (CLEAR_R, common_clear_point_exists, conflict_pairs,  # noqa: E402
                        decision_region_containment, enclosing_radius)


class CounterexampleTests(unittest.TestCase):
    def test_equilateral_38m_triangle_is_not_jointly_clearable(self):
        r = 38. / math.sqrt(3.)                    # circumradius of a 38 m triangle
        pts = np.array([[r, 0.],
                        [r * math.cos(2 * math.pi / 3), r * math.sin(2 * math.pi / 3)],
                        [r * math.cos(4 * math.pi / 3), r * math.sin(4 * math.pi / 3)]])
        for i, j in ((0, 1), (1, 2), (0, 2)):
            self.assertLessEqual(float(np.linalg.norm(pts[i] - pts[j])), 2 * CLEAR_R + 1e-6,
                                 'every pair must be within 40 m')
        self.assertAlmostEqual(enclosing_radius(pts), r, places=6)
        self.assertGreater(r, CLEAR_R)
        self.assertFalse(common_clear_point_exists(pts),
                         'pairwise 20 m clearance must not imply a joint clear point')
        self.assertEqual(conflict_pairs(pts), 0, 'pairwise rule alone sees no conflict')

    def test_interior_concentration_misses_the_extreme_point(self):
        interior = np.array([[0., 0.], [1., 0.], [0., 1.], [1., 1.]]) / 10.
        extreme = np.array([200., 0.])
        self.assertTrue(common_clear_point_exists(interior))
        self.assertFalse(common_clear_point_exists(np.vstack([interior, extreme])),
                         'a concentrated interior set must not hide a missing extreme point')

    def test_area_collapse_without_a_certificate_is_not_better(self):
        """A certified large-area set must not lose to an uncertified thin set."""
        ang = np.linspace(0, 2 * math.pi, 32, endpoint=False)
        certified = 10. * np.column_stack([np.cos(ang), np.sin(ang)])     # area ~314, radius 10
        thin = np.array([[0., 0.], [45., 0.]])                            # area ~0, span 45
        self.assertTrue(common_clear_point_exists(certified))
        self.assertFalse(common_clear_point_exists(thin),
                         'a thin but long set has no common 20 m clear point')

    def test_containment_and_pair_counting(self):
        pts = np.array([[0., 0.], [10., 0.], [0., 10.]])
        self.assertTrue(common_clear_point_exists(pts))
        self.assertEqual(conflict_pairs(pts), 0)
        self.assertAlmostEqual(decision_region_containment([0., 0.], pts), 1.0, places=6)
        self.assertLess(decision_region_containment([100., 0.], pts), 1.0)


if __name__ == '__main__':
    unittest.main()
