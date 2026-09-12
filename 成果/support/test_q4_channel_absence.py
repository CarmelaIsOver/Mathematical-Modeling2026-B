"""Q4 per-channel absence certificate: soundness and structural limits.

The certificate proves that a channel measured with no signal at stations whose
convex hull contains a mesh cell cannot hold a source in that cell. Every station
of both verified layouts is essential to at least one cell, so the certificate
can never skip a measurement: it confirms coverage at the end rather than
removing work. These tests pin that structure down.
"""
import unittest

from coverage_geometry import certify, cell_is_covered, layout_cells
from geometry import search_stations
from backend import LocalBackend
from audit import AuditPort
from joint_search import JointSearchSolver

LAYOUTS = ('radial', 'rings')


class CellGeometryTests(unittest.TestCase):
    def test_runtime_cell_test_matches_the_static_certificate(self):
        for layout in LAYOUTS:
            points = search_stations(4, layout=layout)
            masks, _sizes, _index, centers, halves = layout_cells(points)
            self.assertTrue(certify(points, max_depth=14)['covered'])
            mismatches = 0
            for j, mask in enumerate(masks):
                sensors = [points[k] for k in range(len(points)) if (mask >> k) & 1]
                if not cell_is_covered(centers[j], halves[j], sensors):
                    mismatches += 1
            self.assertEqual(mismatches, 0, layout)

    def test_every_station_is_essential_for_some_cell(self):
        # Removing any single station leaves at least one cell uncertifiable, so
        # that station must measure every unresolved channel. Per-channel
        # certificates therefore cannot skip measurements or station visits.
        for layout in LAYOUTS:
            points = search_stations(4, layout=layout)
            masks, _sizes, _index, centers, halves = layout_cells(points)
            essential = set()
            for j, mask in enumerate(masks):
                members = [k for k in range(len(points)) if (mask >> k) & 1]
                for k in members:
                    rest = [points[q] for q in members if q != k]
                    if not cell_is_covered(centers[j], halves[j], rest):
                        essential.add(k)
            self.assertEqual(essential, set(range(len(points))), layout)


class RuntimeAbsenceTests(unittest.TestCase):
    def test_certificate_is_sound_but_adds_no_skips(self):
        backend = LocalBackend(1910016, 4)
        self.assertEqual(len(backend.sources), 10)
        port = AuditPort(backend)
        solver = JointSearchSolver(port, 4, certify_channel_absence=True)
        result = solver.run()
        self.assertEqual(result['cleared'], 10)
        self.assertTrue(port.exited)
        # The ten non-source channels are proven absent over the whole disk,
        # yet no measurement is skipped because every site is essential.
        self.assertEqual(result['channels_certified_absent'], 10)
        self.assertEqual(result['absence_skipped_measurements'], 0)
        self.assertEqual(result['discovery_closed_by_absence'], 0)

    def test_default_arm_does_not_build_the_certificate(self):
        solver = JointSearchSolver(None, 4)
        self.assertFalse(solver.certify_channel_absence)
        self.assertEqual(solver.absent_channels, set())
        self.assertFalse(hasattr(solver, 'cell_ok'))


if __name__ == '__main__':
    unittest.main()
