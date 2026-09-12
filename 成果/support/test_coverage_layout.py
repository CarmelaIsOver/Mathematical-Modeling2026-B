"""Continuous mesh certificate and runtime equivalence for compact Q4 coverage."""
import unittest,math,json,base64,types,sys,contextlib,io,tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
from geometry import search_stations,distance_origin_triangle
from solver import Solver
from active_localization import ActiveLocalizationSolver
from backend import LocalBackend
from audit import AuditPort
import run as entry

def compressed_stations():
    return search_stations(4,layout='compact')

class CompactCoverageTests(unittest.TestCase):
    def test_compressed_mesh_covers_disk_with_short_edges(self):
        original=search_stations(4);moved=compressed_stations()
        h=950.;a=np.array([h,0.]);b=np.array([h/2,h*math.sqrt(3)/2])
        triangles=[];edges={};signed_area=0.
        for i in range(-7,8):
            for j in range(-7,8):
                base=i*a+j*b
                for offsets in ([np.zeros(2),a,b],[a,a+b,b]):
                    t=base+np.array(offsets)
                    if distance_origin_triangle(t)>1800+1e-8:continue
                    indices=[int(np.argmin(np.linalg.norm(original-p,axis=1))) for p in t]
                    self.assertLess(np.max(np.linalg.norm(original[indices]-t,axis=1)),1e-6)
                    q=moved[indices]
                    ab,ac=q[1]-q[0],q[2]-q[0]
                    area=(ab[0]*ac[1]-ab[1]*ac[0])/2
                    self.assertGreater(area,1e-6);signed_area+=area
                    self.assertLessEqual(np.max(np.linalg.norm(q-np.roll(q,1,axis=0),axis=1)),1000.)
                    triangles.append(q)
                    for first,last in zip(indices,np.roll(indices,-1)):
                        key=tuple(sorted((first,int(last))));edges[key]=edges.get(key,0)+1
        self.assertEqual(len(triangles),42)
        boundary=[edge for edge,count in edges.items() if count==1]
        ids=sorted({i for edge in boundary for i in edge},key=lambda i:math.atan2(moved[i,1],moved[i,0]))
        self.assertEqual(len(boundary),len(ids))
        chain=[tuple(sorted((i,int(j)))) for i,j in zip(ids,np.roll(ids,-1))]
        self.assertEqual(set(boundary),set(chain))
        polygon=moved[ids];boundary_area=0.
        for first,last in zip(polygon,np.roll(polygon,-1,axis=0)):
            vector=last-first
            fraction=np.clip(-first@vector/(vector@vector),0,1)
            self.assertGreater(np.linalg.norm(first+fraction*vector),1800.)
            cross=first[0]*last[1]-first[1]*last[0]
            self.assertGreater(cross,0.);boundary_area+=cross/2
        self.assertAlmostEqual(signed_area,boundary_area,places=5)
        # Positive face orientations and a simple polar boundary give degree one:
        # the deformed triangulation fills the boundary without folds or holes.
        inside=np.linalg.norm(original,axis=1)<=1800
        self.assertTrue(np.array_equal(original[inside],moved[inside]))

    def test_runtime_matches_frozen_layout_and_full_action_trace(self):
        root=Path(__file__).resolve().parent
        fixture=json.loads((root/'results/coverage_optimization/compressed_sources.json').read_text())
        source=base64.b64decode(fixture['tmp/coverage_experiment.py']['bytes_base64']).decode('utf-8')
        frozen=types.ModuleType('frozen_coverage_experiment')
        frozen.__file__=str(root.parents[1]/'tmp/coverage_experiment.py')
        exec(compile(source,frozen.__file__,'exec'),frozen.__dict__)
        self.assertTrue(np.array_equal(compressed_stations(),frozen.compressed_stations()))
        for cls in (Solver,ActiveLocalizationSolver):
            for seed in (1500000,1600018):
                traces=[]
                for use_entry in (False,True):
                    backend=LocalBackend(seed,4);port=AuditPort(backend)
                    solver=cls(port,4,coverage_layout='compact' if use_entry else 'original')
                    if not use_entry:solver.stations=frozen.compressed_stations()
                    result=solver.run()
                    self.assertEqual(result['cleared'],len(backend.sources))
                    self.assertTrue(port.exited);traces.append(backend.trace)
                self.assertEqual(traces[0],traces[1])

    def test_entry_records_layout_and_rejects_unverified_spacing(self):
        for strategy in ('standard','paper'):
            with tempfile.TemporaryDirectory() as folder:
                with patch.object(sys,'argv',['run.py','--mode','official','--problem','4',
                    '--strategy',strategy,'--layout','compact','--robot-id','TEST_PLACEHOLDER','--output',folder]), \
                    patch.object(entry,'HTTPBackend',side_effect=lambda *args:LocalBackend(1500000,4)), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                    entry.main()
                result=json.loads(next(Path(folder).glob('client_*.json')).read_text())
                self.assertEqual(result['coverage_layout'],'compact')
                self.assertTrue(result['complete'] and result['normal_exit'])
                self.assertIn('layout=compact',output.getvalue())
        for problem,spacing in ((3,950),(4,999)):
            with self.assertRaises(ValueError):search_stations(problem,spacing,layout='compact')
