"""Q3 scheduler integration, completion invariants and frozen trace checks."""
import base64,contextlib,io,json,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from backend import LocalBackend
from audit import AuditPort
from solver import Solver
from omni_search import OmniSearchSolver
import run as entry


class OmniSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).resolve().parent
        fixture=json.loads((root/'results/q3_scheduling/frozen_sources.json').read_text())
        source=base64.b64decode(fixture['tmp/q3_schedule_experiment.py']['bytes_base64']).decode()
        cls.frozen=types.ModuleType('frozen_q3_schedule')
        cls.frozen.__file__=str(root.parents[1]/'tmp/q3_schedule_experiment.py')
        exec(compile(source,cls.frozen.__file__,'exec'),cls.frozen.__dict__)

    def test_production_matches_frozen_candidate_full_trace(self):
        for seed in (2200000,2200013,2200039):
            traces=[]
            for prototype in (True,False):
                b=LocalBackend(seed,3);port=AuditPort(b)
                solver=self.frozen.ScheduleSolver(port,'tour_select') if prototype else OmniSearchSolver(port,3)
                r=solver.run();self.assertEqual(r['cleared'],len(b.sources));self.assertTrue(port.exited)
                traces.append(b.trace)
            self.assertEqual(traces[0],traces[1])

    def test_small_count_finishes_all_sites_and_all_known_targets(self):
        b=LocalBackend(2400000,3,n=10,radius=1000.,error_mode='plus');port=AuditPort(b)
        solver=OmniSearchSolver(port,3);r=solver.run()
        self.assertEqual(r['cleared'],10);self.assertTrue(port.exited)
        self.assertEqual(sorted(solver.visited),list(range(7)))
        self.assertFalse(any(c not in solver.cleared for c in solver.deferred))
        for c in set(range(1,21))-set(b.sources):
            self.assertEqual(len(solver.measured[c]),7)

    def test_skip_requires_a_known_source_and_keeps_its_task(self):
        solver=OmniSearchSolver(None,3)
        self.assertFalse(solver.skip_station_measurement(7,np.zeros(2)))
        solver.deferred[7]=1
        with patch.object(solver,'region',return_value=(None,np.array([3000.,0.]),100.)):
            self.assertTrue(solver.skip_station_measurement(7,np.zeros(2)))
        with patch.object(solver,'region',return_value=(None,np.zeros(2),19.)):
            self.assertTrue(solver.skip_station_measurement(7,np.zeros(2)))
        self.assertIn(7,solver.deferred);self.assertNotIn(7,solver.cleared)

    def test_no_mid_search_forced_visits(self):
        class Observed(OmniSearchSolver):
            def locate(self,c):
                if self.pending_stations:
                    if self.diagnostics['forced_targets']!=0:raise AssertionError('Premature forced visit')
                return super().locate(c)
        b=LocalBackend(2200013,3);r=Observed(AuditPort(b),3).run()
        self.assertEqual(r['cleared'],len(b.sources))

    def test_official_default_entry_policy_and_log(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(sys,'argv',['run.py','--mode','official','--problem','3',
                 '--robot-id','TEST_PLACEHOLDER','--output',folder]), \
                 patch.object(entry,'HTTPBackend',side_effect=lambda *args:LocalBackend(2200000,3)), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                entry.main()
            r=json.loads(next(Path(folder).glob('client_*.json')).read_text())
            self.assertEqual((r['strategy'],r['coverage_layout']),('integrated','tight'))
            self.assertEqual(r['service_policy'],'adaptive')
            self.assertEqual(r['scheduling_policy'],'joint_route')
            self.assertTrue(r['complete'] and r['normal_exit'])
        with self.assertRaises(ValueError):OmniSearchSolver(None,4)


if __name__=='__main__':unittest.main()
