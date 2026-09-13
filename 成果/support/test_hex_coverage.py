"""Continuous coverage, frozen candidate traces and worst-angle execution."""
import hashlib,json,math,unittest
from pathlib import Path
import numpy as np
from geometry import search_stations
from backend import LocalBackend
from audit import AuditPort
from test_history_support import FrozenOmniSearchSolver as OmniSearchSolver

class HexCoverageTests(unittest.TestCase):
    def test_continuous_radial_coverage_bound(self):
        sites=search_stations(3,layout='hex')
        self.assertEqual(sites.shape,(7,2));self.assertTrue(np.array_equal(sites[0],[0.,0.]))
        self.assertTrue(np.allclose(np.linalg.norm(sites[1:],axis=1),1125.,rtol=0,atol=1e-10))
        angles=np.unwrap(np.arctan2(sites[1:,1],sites[1:,0]));gaps=np.diff(np.r_[angles,angles[0]+2*np.pi])
        half_angle=max(gaps)/2
        # Origin covers [0,1000]; the convex squared-distance bound on
        # [1000,1800] is maximized at an endpoint, not a sampled grid.
        bound=max(p*p+1125**2-2*p*1125*math.cos(half_angle) for p in (1000,1800))
        self.assertLess(math.sqrt(bound),999.12)
        with self.assertRaises(ValueError):search_stations(4,layout='hex')

    def test_final_candidate_traces_match(self):
        fixtures=json.loads((Path(__file__).parent/'results/scan_route/adopted_trace_fixtures.json').read_text())
        for f in fixtures:
            b=LocalBackend(f['seed'],3);p=AuditPort(b)
            r=OmniSearchSolver(p,3,coverage_layout='hex',service_policy='adaptive').run()
            digest=hashlib.sha256(json.dumps(b.trace,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            self.assertEqual(digest,f['trace_sha256']);self.assertEqual(r['mean_time_s'],f['mean_time_s'])
            self.assertTrue(p.exited)

    def test_worst_angle_boundary_sources_and_unknown_channels(self):
        for error in ('plus','minus'):
            b=LocalBackend(4500000,3,n=12,radius=1000,error_mode=error)
            for i,x in enumerate(b.sources.values()):
                angle=np.pi/6+(i%6)*np.pi/3;x['p']=(1800-i//6)*np.array([np.cos(angle),np.sin(angle)])
            p=AuditPort(b);s=OmniSearchSolver(p,3,coverage_layout='hex',service_policy='adaptive');r=s.run()
            self.assertEqual(r['cleared'],12);self.assertTrue(p.exited);self.assertEqual(r['stations_visited'],7)
            for c in set(range(1,21))-set(b.sources):
                for q in s.stations:self.assertTrue(any(np.array_equal(q,m) for m in s.measured[c]))

if __name__=='__main__':unittest.main()
