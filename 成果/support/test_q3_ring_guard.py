"""Q3 guarded ring shrink: opt-in switch, completeness and site coverage."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from backend import LocalBackend
from audit import AuditPort
from omni_search import OmniSearchSolver
import run as entry


class RingGuardTests(unittest.TestCase):
    def test_default_off_leaves_the_team_layout(self):
        solver = OmniSearchSolver(None, 3)
        self.assertEqual(solver.ring_guard, 'off')
        self.assertFalse(solver.ring_activated)

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            OmniSearchSolver(None, 3, ring_guard='turbo')

    def test_guard_activates_and_scans_every_site_once(self):
        backend = LocalBackend(3470000, 3)
        port = AuditPort(backend)
        solver = OmniSearchSolver(port, 3, ring_guard='aggressive')
        result = solver.run()
        self.assertEqual(result['cleared'], len(backend.sources))
        self.assertTrue(port.exited)
        self.assertEqual(result['ring_activated'], 1)
        # Every site visited exactly once: the centre is never re-queued.
        self.assertEqual(sorted(solver.visited), list(range(len(solver.stations))))
        # The certified ring keeps every source within 1000 m of some site.
        for source in backend.sources.values():
            distance = float(np.min(np.linalg.norm(solver.stations - source['p'], axis=1)))
            self.assertLessEqual(distance, 1000. + 1e-6)

    def test_guard_modes_differ_in_required_evidence(self):
        aggressive = OmniSearchSolver(None, 3, ring_guard='aggressive')
        conservative = OmniSearchSolver(None, 3, ring_guard='conservative')
        self.assertEqual(aggressive.min_origin_seen, 1)
        self.assertEqual(conservative.min_origin_seen, 6)
        self.assertEqual(aggressive.skip_known_radius, 1200.)

    def test_entry_exposes_the_switch(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(sys, 'argv', ['run.py', '--mode', 'official', '--problem', '3',
                 '--strategy', 'integrated', '--q3-ring-guard', 'aggressive',
                 '--robot-id', 'TEST_PLACEHOLDER', '--output', folder]), \
                 patch.object(entry, 'HTTPBackend',
                              side_effect=lambda *args: LocalBackend(3470000, 3)), \
                 contextlib.redirect_stdout(io.StringIO()):
                entry.main()
            r = json.loads(next(Path(folder).glob('client_*.json')).read_text())
            self.assertEqual(r['q3_ring_guard'], 'aggressive')
            self.assertEqual(r['ring_activated'], 1)
            self.assertTrue(r['normal_exit'])

    def test_entry_rejects_the_switch_outside_q3_integrated(self):
        for argv in (['run.py', '--mode', 'official', '--problem', '4',
                      '--q3-ring-guard', 'aggressive', '--robot-id', 'TEST'],
                     ['run.py', '--mode', 'offline', '--problem', '3',
                      '--strategy', 'paper', '--q3-ring-guard', 'conservative']):
            with patch.object(sys, 'argv', argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    entry.main()


if __name__ == '__main__':
    unittest.main()
