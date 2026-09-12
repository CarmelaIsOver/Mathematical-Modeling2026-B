import unittest
import numpy as np
from audit import AuditPort
from backend import LocalBackend
from solver import Solver,safe_clear_point,open_route


class ControllerTests(unittest.TestCase):
    def test_safe_points_cover_entire_region(self):
        for r in (0,5,19,19.99):
            poly=np.array([[r,0],[0,r],[-r,0],[0,-r]])
            for position in ([100,20],[0,0],[-30,10]):
                q=safe_clear_point(position,np.zeros(2),r)
                self.assertLessEqual(np.max(np.linalg.norm(poly-q,axis=1)),19.990001)

    def test_open_route_preserves_all_tasks(self):
        points=np.random.default_rng(75).normal(size=(24,2))*1000
        order=open_route(points,np.array([0,0]))
        self.assertEqual(sorted(order),list(range(24)))

    def test_ten_sources_needs_complete_coverage(self):
        for problem in (3,4):
            b=LocalBackend(800001,problem,n=10,all_directional=True,radius=1000.)
            port=AuditPort(b);s=Solver(port,problem);r=s.run()
            self.assertEqual(r['cleared'],10)
            self.assertEqual(r['stations_visited'],len(s.stations))
            self.assertTrue(port.exited)
            self.assertFalse(any(c not in s.cleared for c in s.deferred))

    def test_no_new_action_after_unknown_failure(self):
        class Broken:
            virtual_time=0.;exited=False
            def enter(self):return {'accepted':True,'virtual_time_s':0.,'remaining_real_duration_s':1200}
            def action(self,*args):raise ConnectionError('Response unknown')
            def exit(self):self.exited=True
        b=Broken()
        with self.assertRaises(ConnectionError):Solver(b,3).run()
        self.assertFalse(b.exited)

    def test_audit_requires_valid_exit_and_has_no_truth_interface(self):
        b=LocalBackend(2,3);b.sources={};a=AuditPort(b);a.enter()
        a.action('/measure',[300,400],1);a.action('/measure',[300,400],2)
        a.action('/clear',[300,0],3);a.action('/measure',[300,0],2);a.exit()
        self.assertEqual(a.virtual_time,199)
        with self.assertRaises(AttributeError):getattr(a,'sources')
        with self.assertRaises(RuntimeError):a.action('/measure',[0,0],1)

if __name__=='__main__':unittest.main()
