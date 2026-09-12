"""Independent checks of the Q4 covering certificate and runtime integration."""
import contextlib,hashlib,io,itertools,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from coverage_geometry import certify
from geometry import search_stations
from backend import LocalBackend
from audit import AuditPort
from joint_search import JointSearchSolver
import run as entry

ROOT=Path(__file__).resolve().parent


class RingCoverageTests(unittest.TestCase):
    def test_independent_continuous_certificate(self):
        points=search_stations(4,layout='rings');self.assertEqual(len(points),22)
        proof=json.loads((ROOT/'results/q4_adaptive/coverage_proof.json').read_text())
        self.assertTrue(proof['covered'])
        leaves={(tuple(c['center']),c['half']):c for c in proof['cells']};seen=set();cache={}
        def visit(center,half,depth):
            key=(tuple(center),half)
            if key in leaves:
                self.assertNotIn(key,seen);seen.add(key);mask=leaves[key]['mask']
                ids=[i for i in range(len(points)) if mask & (1<<i)]
                sensors=points[ids]
                corners=np.asarray(center)+half*np.array([[-1,-1],[-1,1],[1,-1],[1,1]])
                self.assertLess(np.max(np.linalg.norm(sensors[:,None,:]-corners[None,:,:],axis=2)),1000.)
                if mask not in cache:
                    triples=np.array(list(itertools.combinations(range(len(sensors)),3)))
                    t=sensors[triples];u=t[:,1]-t[:,0];v=t[:,2]-t[:,0]
                    det=u[:,0]*v[:,1]-u[:,1]*v[:,0];valid=np.abs(det)>1e-8
                    cache[mask]=(t[valid,0],u[valid],v[valid],det[valid])
                # Independently express each corner as a convex combination
                # of THREE eligible sites, without using the hull implementation.
                origin,u,v,det=cache[mask]
                for p in corners:
                    d=p-origin
                    a=(d[:,0]*v[:,1]-d[:,1]*v[:,0])/det
                    b=(u[:,0]*d[:,1]-u[:,1]*d[:,0])/det
                    self.assertTrue(np.any((a>=-1e-12)&(b>=-1e-12)&(a+b<=1+1e-12)))
                return
            nearest=np.maximum(np.abs(center)-half,0)
            if np.dot(nearest,nearest)>1800.**2+1e-6:return
            self.assertLess(depth,proof['depth'])
            for offset in ((-1,-1),(-1,1),(1,-1),(1,1)):
                visit(np.asarray(center)+half/2*np.array(offset),half/2,depth+1)
        visit(np.zeros(2),1800.,0)
        self.assertEqual(len(seen),len(leaves))
        self.assertTrue(certify(points,max_depth=12)['covered'])

    def test_missing_sites_and_insufficient_work_are_not_certified(self):
        points=search_stations(4,layout='rings')
        self.assertFalse(certify(points[:8],max_depth=6)['covered'])
        self.assertFalse(certify(points,max_cells=1)['covered'])

    def test_frozen_full_action_digests(self):
        fixtures=json.loads((ROOT/'results/q4_adaptive/trace_fixtures.json').read_text())
        for seed,fixture in fixtures.items():
            b=LocalBackend(int(seed),4);port=AuditPort(b)
            r=JointSearchSolver(port,4,coverage_layout='rings').run()
            digest=hashlib.sha256(json.dumps(b.trace,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            self.assertEqual(digest,fixture['trace_sha256'])
            self.assertEqual(r['cleared'],len(b.sources));self.assertTrue(port.exited)

    def test_observing_all_sixteen_cancels_search_but_not_clearance(self):
        b=LocalBackend(2700000,4,n=16)
        for i,s in enumerate(b.sources.values()):
            a=2*np.pi*i/16;s['p']=200*np.array([np.cos(a),np.sin(a)]);s['direction']=None
        port=AuditPort(b);solver=JointSearchSolver(port,4,coverage_layout='rings');r=solver.run()
        self.assertEqual(r['cleared'],16);self.assertTrue(port.exited)
        self.assertEqual(r['stations_visited'],1)
        self.assertEqual(r['coverage_sites_cancelled'],21)
        self.assertFalse(any(s['alive'] for s in b.sources.values()))

    def test_ten_targets_still_scan_every_unknown_channel(self):
        b=LocalBackend(2700000,4,n=10,radius=1000.,all_directional=True)
        port=AuditPort(b);solver=JointSearchSolver(port,4,coverage_layout='rings');r=solver.run()
        self.assertEqual(r['cleared'],10);self.assertTrue(port.exited)
        self.assertEqual(r['stations_visited'],22);self.assertEqual(r['coverage_sites_cancelled'],0)
        for c in set(range(1,21))-set(b.sources):self.assertEqual(len(solver.measured[c]),22)

    def test_official_entry_records_new_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(sys,'argv',['run.py','--mode','official','--problem','4','--layout','rings',
                 '--robot-id','TEST_PLACEHOLDER','--output',folder]), \
                 patch.object(entry,'HTTPBackend',side_effect=lambda *args:LocalBackend(2500000,4)), \
                 contextlib.redirect_stdout(io.StringIO()):entry.main()
            r=json.loads(next(Path(folder).glob('client_*.json')).read_text())
            self.assertEqual(r['coverage_layout'],'rings')
            self.assertTrue(r['complete'] and r['normal_exit'])


if __name__=='__main__':unittest.main()
