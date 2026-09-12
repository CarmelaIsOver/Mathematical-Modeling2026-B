"""Integration tests for the opt-in paper strategy; never contact a live server."""
import contextlib, io, json, math, sys, tempfile, types, unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from active_localization import ActiveLocalizationSolver, outcomes, radius_bound
from audit import AuditPort
from backend import LocalBackend
from geometry import bearing_clip, EPS_DEG
import run as entry

ROOT=Path(__file__).resolve().parent


class PaperEntryTests(unittest.TestCase):
    def test_frozen_candidate_and_runtime_have_identical_actions(self):
        fixture=json.loads((ROOT/'results/paper_localization/frozen_sources.json').read_text(encoding='utf-8'))
        frozen=types.ModuleType('frozen_paper_candidate')
        frozen.__file__=str(ROOT.parents[1]/'tmp/paper_experiment.py')
        exec(compile(fixture['tmp/paper_experiment.py']['source'],frozen.__file__,'exec'),frozen.__dict__)
        for problem in (3,4):
            for seed in (940000,940130,940169):
                traces=[]
                for cls in (frozen.PaperSolver,ActiveLocalizationSolver):
                    backend=LocalBackend(seed,problem);port=AuditPort(backend)
                    result=cls(port,problem).run()
                    self.assertEqual(result['cleared'],len(backend.sources))
                    self.assertTrue(port.exited)
                    traces.append(backend.trace)
                self.assertEqual(traces[0],traces[1])

    def test_official_entry_dispatch_and_record_with_mock_backend(self):
        for problem in (3,4):
            with tempfile.TemporaryDirectory() as folder:
                with patch.object(sys,'argv',['run.py','--mode','official','--problem',str(problem),
                    '--strategy','paper','--robot-id','TEST_PLACEHOLDER','--output',folder]), \
                    patch.object(entry,'HTTPBackend',side_effect=lambda *args:LocalBackend(940000,problem)), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                    entry.main()
                result=json.loads(next(Path(folder).glob('client_*.json')).read_text())
                self.assertEqual(result['strategy'],'paper')
                self.assertTrue(result['complete'] and result['normal_exit'])
                self.assertGreater(result['paper_measurements_selected'],0)
                self.assertIn('strategy=paper, mode=official',output.getvalue())

    def test_positive_output_bounds(self):
        rng=np.random.default_rng(4421)
        for widths in ((700,10),(45,30),(25,25)):
            for rotation in (0,.7,2.4):
                angles=np.linspace(0,2*math.pi,16,endpoint=False)
                p=np.column_stack((widths[0]*np.cos(angles),widths[1]*np.sin(angles)))
                matrix=np.array([[math.cos(rotation),-math.sin(rotation)],[math.sin(rotation),math.cos(rotation)]])
                p=p@matrix.T
                for q in (np.array([0.,0.]),np.array([800.,90.]),np.array([0.,40.]),np.array([-50.,-100.])):
                    circles=[radius_bound(poly) for poly,w in outcomes(p,q)]
                    for _ in range(40):
                        weights=rng.random(len(p));weights/=weights.sum();g=weights@p
                        beta=math.degrees(math.atan2(g[1]-q[1],g[0]-q[0]))+rng.choice([-EPS_DEG,0.,EPS_DEG])
                        exact=bearing_clip(p,q,beta)
                        self.assertTrue(len(exact)>0)
                        self.assertTrue(any(np.max(np.linalg.norm(exact-c,axis=1))<=r+1e-6 for r,c in circles))


if __name__=='__main__':unittest.main()
