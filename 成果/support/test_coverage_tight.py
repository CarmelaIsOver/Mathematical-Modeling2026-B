"""Independent checks of the Q3 eight-site tight coverage layout.

Three mutually independent routes to the same conclusion:
  * the closed-form bound p <= 2000 cos(phi) derived in geometry.py;
  * a dense polar sweep that knows nothing about that algebra;
  * a continuous quadtree subdivision written out here.
The reception rule is taken from the problem statement - reception is
guaranteed only out to 1000m - not from any module under test. Note that
coverage_geometry.certify is NOT applicable: it tests Q4's convex-hull
condition and returns False for every omni layout of this size, including the
'original' Q3 layout that shipped before this one.
"""
import math, unittest
import numpy as np
from geometry import search_stations

GUARANTEED = 1000.0
DISK = 1800.0


def nearest_neighbour_tour(points):
    """Open tour from the origin, as walked by the route heuristics."""
    pending = [p for p in np.asarray(points, dtype=float)]
    current = np.zeros(2)
    total = 0.0
    while pending:
        j = min(range(len(pending)), key=lambda i: np.linalg.norm(pending[i] - current))
        total += float(np.linalg.norm(pending[j] - current))
        current = pending.pop(j)
    return total


class TightLayoutShapeTests(unittest.TestCase):
    def setUp(self):
        self.points = search_stations(3, layout='tight')

    def test_origin_plus_seven_evenly_spaced_at_1000m(self):
        self.assertEqual(len(self.points), 8)
        self.assertTrue(np.allclose(self.points[0], [0., 0.]))
        self.assertTrue(np.allclose(np.linalg.norm(self.points[1:], axis=1), 1000.))
        angles = np.sort(np.degrees(np.arctan2(self.points[1:, 1], self.points[1:, 0])) % 360)
        gaps = np.diff(np.concatenate([angles, angles[:1] + 360]))
        self.assertTrue(np.allclose(gaps, 360. / 7))

    def test_rejected_for_q4(self):
        with self.assertRaises(ValueError):
            search_stations(4, layout='tight')

    def test_tour_is_shorter_than_the_hexagon_it_replaces(self):
        tight = nearest_neighbour_tour(self.points[1:])
        old = nearest_neighbour_tour(search_stations(3, layout='original')[1:])
        self.assertLess(tight, old)
        self.assertAlmostEqual(tight, 6207., delta=2.)
        self.assertAlmostEqual(old, 9353., delta=2.)


class TightLayoutCoverageTests(unittest.TestCase):
    """Coverage, by three independent arguments."""

    def setUp(self):
        self.points = search_stations(3, layout='tight')

    def test_closed_form_bound_exceeds_the_task_radius(self):
        """p <= 2000 cos(phi), weakest at phi = pi/7, must exceed 1800m."""
        worst_phi = math.pi / 7
        self.assertAlmostEqual(2000 * math.cos(worst_phi), 1801.9377, places=3)
        self.assertGreater(2000 * math.cos(worst_phi), DISK)

    def test_worst_case_rim_point_is_within_reception(self):
        """The rim point half-way between two spokes, checked by cosine rule."""
        d = math.sqrt(DISK ** 2 + 1000. ** 2 - 2 * 1000. * DISK * math.cos(math.pi / 7))
        self.assertAlmostEqual(d, 998.2545, places=3)
        self.assertLess(d, GUARANTEED)
        # And the same point measured directly against the built layout.
        q = DISK * np.array([math.cos(math.pi / 7), math.sin(math.pi / 7)])
        self.assertAlmostEqual(float(np.min(np.linalg.norm(self.points - q, axis=1))),
                               998.2545, places=3)

    def test_dense_polar_sweep_finds_no_uncovered_point(self):
        """Independent of the algebra: sample the disk and the rim closely."""
        worst = 0.0
        worst_at = None
        for k in range(2 * 7 * 180):
            theta = 2 * math.pi * k / (2 * 7 * 180)
            u = np.array([math.cos(theta), math.sin(theta)])
            for r in np.linspace(0.0, DISK, 200):
                q = r * u
                d = float(np.min(np.linalg.norm(self.points - q, axis=1)))
                if d > worst:
                    worst, worst_at = d, q
        self.assertLess(worst, GUARANTEED,
                        msg='uncovered point %s at %.4f m' % (worst_at, worst))
        # The sweep must find the rim point the algebra predicts.
        self.assertAlmostEqual(worst, 998.2545, delta=0.5)

    def test_quadtree_distance_certificate_agrees(self):
        """A continuous subdivision certificate for the Q3 distance rule.

        coverage_geometry.certify is deliberately not used here: it implements
        Q4's convex-hull condition, which no omni layout of this size satisfies
        (it reports False for the existing 'original' Q3 layout too). Q3 only
        needs the distance rule, so the subdivision is written out here.
        """
        centres = np.zeros((1, 2))
        half = DISK
        for _ in range(14):
            # Discard cells with no point of the task disk.
            nearest = np.maximum(np.abs(centres) - half, 0.0)
            centres = centres[(nearest * nearest).sum(axis=1) <= DISK ** 2 + 1e-6]
            if not len(centres):
                break
            # A site covers a whole cell when it reaches the far corner.
            far = np.abs(self.points[None, :, :] - centres[:, None, :]) + half
            covered = ((far * far).sum(axis=2) < (GUARANTEED - 1e-6) ** 2).any(axis=1)
            centres = centres[~covered]
            if not len(centres):
                break
            half /= 2
            shifts = half * np.array([[-1., -1.], [-1., 1.], [1., -1.], [1., 1.]])
            centres = (centres[:, None, :] + shifts[None, :, :]).reshape(-1, 2)
        self.assertEqual(len(centres), 0,
                         msg='%d cells unresolved, e.g. %s' % (len(centres),
                                                              centres[0] if len(centres) else None))

    def test_dropping_the_origin_leaves_the_centre_uncovered(self):
        """The origin is load-bearing, so it must not be treated as optional."""
        ring = self.points[1:]
        # Every ring site sits at exactly the guaranteed radius from the origin,
        # so without the origin the centre is only reachable by a source that
        # happens to carry more than the guaranteed 1000m. Tolerance is for
        # floating point on the ring radius itself, not physical slack.
        self.assertGreaterEqual(float(np.min(np.linalg.norm(ring, axis=1))), GUARANTEED - 1e-9)

    def test_a_smaller_ring_radius_would_not_cover_the_rim(self):
        """r must stay large enough that 2r cos(pi/7) reaches past 1800m."""
        minimum = DISK / (2 * math.cos(math.pi / 7))
        self.assertAlmostEqual(minimum, 998.9246, places=3)
        self.assertLess(minimum, 1000.)
        # Five metres inside that bound, the mid-spoke rim point is out of reach.
        r = minimum - 5.
        q = DISK * np.array([math.cos(math.pi / 7), math.sin(math.pi / 7)])
        ring = r * np.array([[math.cos(2 * math.pi * k / 7), math.sin(2 * math.pi * k / 7)]
                             for k in range(7)])
        sites = np.vstack([np.zeros((1, 2)), ring])
        self.assertGreater(float(np.min(np.linalg.norm(sites - q, axis=1))), GUARANTEED)


if __name__ == '__main__':
    unittest.main()
