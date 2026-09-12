"""Q3 small-region optical probe: opt-in switch, completeness and command wiring."""
import sys
import unittest
from types import MethodType

from audit import AuditPort
from backend import LocalBackend
from omni_search import OmniSearchSolver
import run as entry


class ProbeTests(unittest.TestCase):
    def _solve(self, seed, **kwargs):
        backend = LocalBackend(seed, 3)
        port = AuditPort(backend)
        solver = OmniSearchSolver(port, 3, ring_guard='aggressive', **kwargs)
        return backend, port, solver

    def test_default_off(self):
        solver = OmniSearchSolver(None, 3)
        self.assertEqual(solver.probe_radius, 0.)
        self.assertEqual(solver.diagnostics['extra_probe_attempts'], 0)

    def test_negative_radius_is_rejected(self):
        with self.assertRaises(ValueError):
            OmniSearchSolver(None, 3, probe_radius=-1.)

    def test_probe_only_fires_inside_the_window(self):
        backend, port, solver = self._solve(3484000, probe_radius=60.)
        seen = []
        original = solver.clear

        def spy(p, c):
            seen.append((solver.diagnostics['extra_probe_attempts'], solver.region(c)[2]))
            return original(p, c)

        solver.clear = MethodType(lambda self, p, c: spy(p, c), solver)
        result = solver.run()
        self.assertEqual(result['cleared'], len(backend.sources))
        self.assertTrue(port.exited)
        self.assertGreater(result['extra_probe_attempts'], 0)
        # A probe increments the attempt counter immediately before clearing, so
        # every counter increase identifies a probe clear: its radius must lie in
        # the open window (19.99, probe_radius].
        probes = [radius for i, (count, radius) in enumerate(seen)
                  if i and count > seen[i - 1][0]]
        self.assertEqual(len(probes), result['extra_probe_attempts'])
        self.assertTrue(all(19.99 < r <= 60. for r in probes))

    def test_probe_window_is_monotone(self):
        small = self._solve(3484003, probe_radius=40.)[2].run()['extra_probe_attempts']
        large = self._solve(3484003, probe_radius=60.)[2].run()['extra_probe_attempts']
        self.assertLessEqual(small, large)

    def test_default_path_stays_bit_identical(self):
        traces = []
        for kwargs in ({}, {'probe_radius': 0.}):
            backend, port, solver = self._solve(3484002, **kwargs)
            solver.run()
            traces.append([{k: (tuple(v) if isinstance(v, list) else v)
                            for k, v in step.items()} for step in backend.trace])
        self.assertEqual(traces[0], traces[1])

    def test_failed_probe_keeps_the_certified_fallback(self):
        backend, port, solver = self._solve(3484001, probe_radius=60.)
        result = solver.run()
        self.assertEqual(result['cleared'], len(backend.sources))
        self.assertTrue(port.exited)
        self.assertEqual(result['fallback'], 0)
        for cert in solver.certificates:
            self.assertLessEqual(cert['vertex_bound_m'], 19.990001)

    def test_cli_gates_the_probe_to_q3_integrated(self):
        argv = sys.argv
        try:
            sys.argv = ['run.py', '--problem', '4', '--q3-probe-radius', '60']
            with self.assertRaises(SystemExit):
                entry.main()
        finally:
            sys.argv = argv


if __name__ == '__main__':
    unittest.main()
