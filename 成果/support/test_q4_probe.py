"""Q4 small-region probe: opt-in window, default preserved, CLI gating."""
import sys
import unittest

from audit import AuditPort
from backend import LocalBackend
from joint_search import JointSearchSolver
import run as entry


class Q4ProbeTests(unittest.TestCase):
    def test_default_window_is_unchanged(self):
        solver = JointSearchSolver(None, 4)
        self.assertEqual(solver.probe_radius, 40.)

    def test_probe_can_be_disabled_for_isolation(self):
        backend = LocalBackend(3485000, 4)
        port = AuditPort(backend)
        solver = JointSearchSolver(port, 4, probe_radius=0.)
        result = solver.run()
        self.assertEqual(result['cleared'], len(backend.sources))
        self.assertEqual(result['small_region_probes'], 0)

    def test_widened_window_probes_at_least_as_often(self):
        counts = []
        for window in (40., 60.):
            backend = LocalBackend(3485001, 4)
            port = AuditPort(backend)
            solver = JointSearchSolver(port, 4, probe_radius=window)
            result = solver.run()
            self.assertEqual(result['cleared'], len(backend.sources))
            counts.append(result['small_region_probes'])
        self.assertLessEqual(counts[0], counts[1])

    def test_cli_gates_the_flag_to_q4_integrated(self):
        argv = sys.argv
        try:
            sys.argv = ['run.py', '--problem', '3', '--q4-probe-radius', '60']
            with self.assertRaises(SystemExit):
                entry.main()
        finally:
            sys.argv = argv


if __name__ == '__main__':
    unittest.main()
