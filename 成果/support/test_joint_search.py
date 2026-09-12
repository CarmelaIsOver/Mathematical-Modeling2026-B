"""Coverage, frozen behavior equivalence and entry integration of Q4 routing."""
import base64,contextlib,io,json,math,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from geometry import search_stations
from joint_search import JointSearchSolver,search_route
from active_localization import ActiveLocalizationSolver
from backend import LocalBackend
from audit import AuditPort
import run as entry


class JointSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).resolve().parent
        fixture=json.loads((root/'results/target400/frozen_sources.json').read_text())
        source=base64.b64decode(fixture['tmp/target400_experiment.py']['bytes_base64']).decode()
        cls.frozen=types.ModuleType('frozen_target_experiment')
        cls.frozen.__file__=str(root.parents[1]/'tmp/target400_experiment.py')
        exec(compile(source,cls.frozen.__file__,'exec'),cls.frozen.__dict__)

    def test_radial_mesh_continuously_covers_entire_disk(self):
        points=search_stations(4,layout='radial')
        self.assertTrue(np.array_equal(points,self.frozen.radial_stations()))
        self.assertEqual(len(points),25)
        faces=self.frozen.radial_faces(points);self.assertEqual(len(faces),36)
        edges={};area=0.
        for face in faces:
            q=points[face];a=q[1]-q[0];b=q[2]-q[0]
            signed=(a[0]*b[1]-a[1]*b[0])/2
            self.assertGreater(signed,1e-6);area+=signed
            self.assertLess(np.max(np.linalg.norm(q-np.roll(q,1,axis=0),axis=1)),1000.)
            for i,j in zip(face,np.roll(face,-1)):
                edge=tuple(sorted((int(i),int(j))));edges[edge]=edges.get(edge,0)+1
        self.assertTrue(all(n in (1,2) for n in edges.values()))
        boundary={e for e,n in edges.items() if n==1}
        ids=sorted({i for e in boundary for i in e},key=lambda i:math.atan2(points[i,1],points[i,0]))
        self.assertEqual(len(ids),12)
        self.assertEqual(boundary,{tuple(sorted((i,int(j)))) for i,j in zip(ids,np.roll(ids,-1))})
        boundary_area=0.
        for p,q in zip(points[ids],np.roll(points[ids],-1,axis=0)):
            d=q-p;t=np.clip(-p@d/(d@d),0,1)
            self.assertGreater(np.linalg.norm(p+t*d),1800.)
            cross=p[0]*q[1]-p[1]*q[0]
            self.assertGreater(cross,0.);boundary_area+=cross/2
        self.assertAlmostEqual(area,boundary_area,places=5)
        # Positive orientation, a simple outer cycle and shared interior edges
        # prove no folds/holes. Every source has a <=1000m enclosing triangle;
        # any closed emitting half-plane contains at least one of its vertices.

    def test_runtime_matches_selected_frozen_prototype(self):
        for seed in (1800000,1800011,1800023):
            traces=[]
            for prototype in (True,False):
                b=LocalBackend(seed,4);port=AuditPort(b)
                s=self.frozen.JointSolver(port,'multitour') if prototype else JointSearchSolver(port,4)
                r=s.run();self.assertEqual(r['cleared'],len(b.sources));self.assertTrue(port.exited)
                self.assertLessEqual(port.max_step_error_s,1e-4);traces.append(b.trace)
            self.assertEqual(traces[0],traces[1])

    def test_small_count_requires_full_coverage_and_source_resolution(self):
        b=LocalBackend(2000000,4,n=10,all_directional=True,radius=1000.)
        port=AuditPort(b);solver=JointSearchSolver(port,4);r=solver.run()
        self.assertEqual(r['cleared'],10);self.assertTrue(port.exited)
        self.assertEqual(sorted(solver.visited),list(range(25)))
        self.assertFalse(any(c not in solver.cleared for c in solver.deferred))
        # Each still-unknown channel must have been measured at every site.
        for c in set(range(1,21))-set(b.sources):
            for p in solver.stations:
                self.assertTrue(any(np.array_equal(p,q) for q in solver.measured[c]))

    def test_route_handles_empty_singleton_and_preserves_all_nodes(self):
        self.assertEqual(search_route([],np.zeros(2)),[])
        self.assertEqual(search_route([[10,20]],np.zeros(2)),[0])
        points=np.random.default_rng(92).normal(size=(30,2))*1000
        self.assertEqual(sorted(search_route(points,np.zeros(2))),list(range(30)))

    def test_default_official_entry_uses_joint_policy_and_reports_it(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(sys,'argv',['run.py','--mode','official','--problem','4',
                 '--robot-id','TEST_PLACEHOLDER','--output',folder]), \
                 patch.object(entry,'HTTPBackend',side_effect=lambda *args:LocalBackend(1800000,4)), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                entry.main()
            r=json.loads(next(Path(folder).glob('client_*.json')).read_text())
            self.assertEqual((r['strategy'],r['coverage_layout']),('integrated','radial'))
            self.assertTrue(r['complete'] and r['normal_exit'])
            self.assertIn('strategy=integrated',output.getvalue())
        with self.assertRaises(ValueError):JointSearchSolver(None,3)
        with self.assertRaises(ValueError):JointSearchSolver(None,4,spacing=999.)

    def test_failed_small_region_probe_still_runs_localization(self):
        solver=JointSearchSolver(None,4)
        with patch.object(solver,'region',return_value=(None,np.zeros(2),30.)), \
             patch.object(solver,'clear',return_value=False), \
             patch.object(ActiveLocalizationSolver,'locate',return_value='continued') as fallback:
            self.assertEqual(solver.locate(7),'continued')
            fallback.assert_called_once_with(7)
        self.assertNotIn(7,solver.cleared)
        self.assertEqual(solver.diagnostics['small_region_successes'],0)


if __name__=='__main__':unittest.main()
