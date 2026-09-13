"""Upstream test suite for the ported adaptive service (teammate commit 66faa29).

Scope note for this fusion round: Q3 only absorbs the negative-range relaxation
(`outside_disk_hull`), so the tests that require the teammate Q3 `tight` layout or the
Q3 adaptive service are marked ``skip`` with that reason. Q4 service tests run against
the local solver (opt-in `service_policy='adaptive'`); the negative-exclusion tests run
against `outside_disk_hull` directly and are extended by ``test_neg_hull.py``.
"""
import contextlib,hashlib,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from backend import LocalBackend
from audit import AuditPort
from solver import Solver
from omni_search import OmniSearchSolver
from joint_search import JointSearchSolver
from localization_service import outside_disk_hull
from coverage_geometry import hull_normals
import run as entry

ROOT=Path(__file__).resolve().parent

class LocalizationServiceTests(unittest.TestCase):
    @unittest.skip('Q3 tight layout + Q3 adaptive service are out of scope for this fusion round (Q3 only absorbs the negative-range relaxation)')
    def test_atomic_entry_restores_previous_layouts_and_behavior(self):
        for problem,layout,ctor in [(3,'tight',OmniSearchSolver),(4,'radial',JointSearchSolver)]:
            expected=ctor(AuditPort(LocalBackend(3500000,problem)),problem,coverage_layout=layout).run()
            with tempfile.TemporaryDirectory() as folder:
                with patch.object(sys,'argv',['run.py','--mode','official','--problem',str(problem),
                    '--service-policy','atomic','--robot-id','TEST_PLACEHOLDER','--output',folder]), \
                     patch.object(entry,'HTTPBackend',side_effect=lambda *args:LocalBackend(3500000,problem)), \
                     contextlib.redirect_stdout(io.StringIO()):entry.main()
                actual=json.loads(next(Path(folder).glob('client_*.json')).read_text())
                self.assertEqual(actual['coverage_layout'],layout)
                self.assertEqual(actual['service_policy'],'atomic')
                self.assertEqual(actual['mean_time_s'],expected['mean_time_s'])

    @unittest.skip('Q3 tight layout + Q3 adaptive service are out of scope for this fusion round (Q3 only absorbs the negative-range relaxation)')
    def test_adopted_candidate_full_traces(self):
        fixtures=json.loads((ROOT/'results/target_pair/adopted_trace_fixtures.json').read_text())
        for f in fixtures:
            b=LocalBackend(f['seed'],f['problem']);port=AuditPort(b)
            ctor=OmniSearchSolver if f['problem']==3 else JointSearchSolver
            s=ctor(port,f['problem'],coverage_layout='tight' if f['problem']==3 else 'rings',service_policy='adaptive')
            r=s.run()
            digest=hashlib.sha256(json.dumps(b.trace,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            self.assertEqual(digest,f['trace_sha256'],f)
            self.assertEqual(r['mean_time_s'],f['mean_time_s']);self.assertTrue(port.exited)

    @unittest.skip('Q3 tight layout + Q3 adaptive service are out of scope for this fusion round (Q3 only absorbs the negative-range relaxation)')
    def test_unknown_channels_keep_full_coverage_and_known_sources_finish(self):
        for problem in (3,4):
            b=LocalBackend(3900000,problem,n=10,radius=1000,all_directional=problem==4)
            p=AuditPort(b);ctor=OmniSearchSolver if problem==3 else JointSearchSolver
            s=ctor(p,problem,coverage_layout='tight' if problem==3 else 'rings',service_policy='adaptive')
            r=s.run();self.assertEqual(r['cleared'],10);self.assertTrue(p.exited)
            self.assertFalse(any(c not in s.cleared for c in s.deferred))
            for c in set(range(1,21))-set(b.sources):
                for q in s.stations:self.assertTrue(any(np.array_equal(q,x) for x in s.measured[c]))

    @unittest.skip('Q3 tight layout + Q3 adaptive service are out of scope for this fusion round (Q3 only absorbs the negative-range relaxation)')
    def test_sixteen_observed_stops_discovery_but_clears_every_source(self):
        b=LocalBackend(3900000,3,n=16)
        for i,x in enumerate(b.sources.values()):
            a=2*np.pi*i/16;x['p']=200*np.array([np.cos(a),np.sin(a)])
        port=AuditPort(b);s=OmniSearchSolver(port,3,coverage_layout='tight',service_policy='adaptive');r=s.run()
        self.assertEqual(r['cleared'],16);self.assertEqual(r['stations_visited'],1)
        self.assertEqual(r['coverage_sites_cancelled'],7);self.assertTrue(port.exited)

    @unittest.skip('Q3 tight layout + Q3 adaptive service are out of scope for this fusion round (Q3 only absorbs the negative-range relaxation)')
    def test_partial_omni_service_has_a_finite_fallback_budget(self):
        s=OmniSearchSolver(None,3,coverage_layout='tight',service_policy='adaptive')
        s.deferred[7]=1
        with patch.object(s,'region',return_value=(None,np.array([400.,0]),200.)), \
             patch.object(s,'next_measure',return_value=np.array([100.,100.])), \
             patch.object(s,'action',return_value={'measure_result':'direction'}) as action, \
             patch.object(Solver,'locate',return_value=None) as fallback:
            for _ in range(5):s.locate(7)
            self.assertEqual(action.call_count,4);fallback.assert_called_once_with(s,7)
        self.assertIn(7,s.deferred);self.assertNotIn(7,s.cleared)

    def test_partial_directional_service_has_a_finite_fallback_budget(self):
        s=JointSearchSolver(None,4,coverage_layout='rings',service_policy='adaptive')
        s.obs[7]=[(np.zeros(2),0.)];s.deferred[7]=1
        with patch.object(s,'region',return_value=(None,np.array([400.,0]),200.)), \
             patch.object(Solver,'next_measure',return_value=np.array([100.,100.])), \
             patch.object(s,'action',return_value={'measure_result':'direction'}) as action, \
             patch.object(s,'locate',return_value=None) as fallback:
            for _ in range(5):s._localization_service.advance_directional(7)
            self.assertEqual(action.call_count,4);fallback.assert_called_once_with(7)
        self.assertIn(7,s.deferred);self.assertNotIn(7,s.cleared)

    @unittest.skip('Q3 tight layout + Q3 adaptive service are out of scope for this fusion round (Q3 only absorbs the negative-range relaxation)')
    def test_negative_observation_invalidates_region_cache_without_new_bearing(self):
        s=OmniSearchSolver(None,3,coverage_layout='tight',service_policy='adaptive')
        s.obs[7]=[(np.zeros(2),0.)];before=s.region(7)[2]
        s._localization_service.record('/measure',np.array([-500.,0]),7,{'measure_result':'no_signal'})
        poly,center,after=s.region(7)
        self.assertLess(after,before);self.assertEqual(len(s.obs[7]),1)
        normals,bounds=hull_normals(poly)
        self.assertTrue(np.all(normals@np.array([1000.,0])<=bounds+1e-6))
        q4=JointSearchSolver(None,4,service_policy='adaptive')
        q4._localization_service.record('/measure',np.zeros(2),7,{'measure_result':'no_signal'})
        self.assertEqual(q4._localization_service.negatives[7],[])
        with self.assertRaises(ValueError):q4._localization_service.omni_region(7)

    def test_exclusion_keeps_all_components_and_boundary_points(self):
        square=np.array([[0.,0],[2000.,0],[2000.,2000.],[0.,2000.]])
        normals,bounds=hull_normals(outside_disk_hull(square,np.zeros(2)))
        for q in [np.array([1000.,0]),np.array([0.,1000]),np.array([800.,800.])]:
            self.assertTrue(np.all(normals@q<=bounds+1e-6))
        self.assertFalse(np.all(normals@np.array([10.,10.])<=bounds))
        strip=np.array([[-1500.,-10.],[1500.,-10.],[1500.,10.],[-1500.,10.]])
        # Keeping a convex superset deliberately keeps the gap between the two
        # remaining components; selecting a single component would be unsafe.
        self.assertTrue(np.array_equal(outside_disk_hull(strip,np.zeros(2)),strip))

    def test_random_outside_samples_are_never_removed(self):
        rng=np.random.default_rng(19361)
        for _ in range(40):
            angles=np.arange(8)*np.pi/4+rng.uniform(0,2*np.pi)
            center=rng.uniform(-500,500,2);poly=center+1400*np.c_[np.cos(angles),np.sin(angles)]
            q=rng.uniform(-800,800,2);new=outside_disk_hull(poly,q)
            normals,bounds=hull_normals(new)
            i=rng.integers(0,8,500);w=rng.random((500,3));w/=w.sum(axis=1)[:,None]
            samples=w[:,0,None]*center+w[:,1,None]*poly[i]+w[:,2,None]*poly[(i+1)%8]
            samples=samples[np.linalg.norm(samples-q,axis=1)>=1000.]
            self.assertTrue(np.all(samples@normals.T<=bounds+1e-6))

    @unittest.skip('Q3 tight layout + Q3 adaptive service are out of scope for this fusion round (Q3 only absorbs the negative-range relaxation)')
    def test_real_omni_source_stays_in_each_computed_region(self):
        for seed in (3900000,3900001,3900002):
            b=LocalBackend(seed,3,radius=1000,error_mode='plus')
            class Observed(OmniSearchSolver):
                def region(self,c):
                    poly,center,radius=super().region(c)
                    hb=hull_normals(poly)
                    if hb is not None:
                        n,bounds=hb
                        if not np.all(n@b.sources[c]['p']<=bounds+1e-5):raise AssertionError('True source was excluded')
                    return poly,center,radius
            port=AuditPort(b);s=Observed(port,3,coverage_layout='tight',service_policy='adaptive')
            self.assertEqual(s.run()['cleared'],len(b.sources));self.assertTrue(port.exited)

if __name__=='__main__':unittest.main()
