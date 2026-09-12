import unittest
import math
from unittest.mock import patch
import study
import numpy as np
from backend import LocalBackend
from audit import AuditPort
from omni_search import OmniSearchSolver
from joint_search import JointSearchSolver
from variants import OmniVariant,DirectionalVariant,FinishStep,ChooseLayout


class PolicyTests(unittest.TestCase):
    def test_disabled_variants_match_baseline_actions(self):
        for problem,old,new in [(3,OmniSearchSolver,OmniVariant),(4,JointSearchSolver,DirectionalVariant)]:
            a=LocalBackend(3200016,problem);b=LocalBackend(3200016,problem)
            old(AuditPort(a),problem).run();new(AuditPort(b),problem).run()
            self.assertEqual(a.trace,b.trace)

    def test_complete_ring_interval(self):
        for radius in [1123,1300]:
            # Center covers r<=1000; radial squared distance is convex on [1000,1800].
            self.assertLess(max(r*r+radius*radius-2*r*radius*math.cos(math.pi/6) for r in [1000,1800]),1000**2)
        with self.assertRaises(ValueError):OmniVariant(None,3,ring_radius=1100)

    def test_guard_keeps_empty_center_trajectory(self):
        a=LocalBackend(3700200,3,n=16,radius=1000)
        b=LocalBackend(3700200,3,n=16,radius=1000)
        for backend in (a,b):
            for i,s in enumerate(backend.sources.values()):
                angle=2*math.pi*i/16
                s['p']=1799.999*np.array([math.cos(angle),math.sin(angle)])
        OmniSearchSolver(AuditPort(a),3).run()
        solver=OmniVariant(AuditPort(b),3,ring_radius=1123.,guard_initial=True)
        solver.run()
        self.assertFalse(solver.ring_activated)
        self.assertEqual(a.trace,b.trace)

    def test_layout_replacement_retains_complete_station_scan(self):
        b=LocalBackend(3500000,4,n=10)
        solver=ChooseLayout(AuditPort(b),4);solver.run()
        self.assertEqual(len(solver.cleared),10)
        self.assertEqual(set(solver.visited),set(range(len(solver.stations))))
        self.assertEqual(len(solver.visited),len(solver.stations))

    def test_guard_rebuilds_pending_for_any_ring_count(self):
        # A guarded switch to a layout with a different station count must keep
        # every unvisited site, otherwise coverage silently loses a sector.
        for ring_count,radius in ((6,1123.),(7,997.5),(8,938.1),(9,903.5)):
            backend=LocalBackend(3210024,3,n=16,radius=1500.)
            for i,s in enumerate(backend.sources.values()):
                if i==0:s['p']=np.array([50.,0.])
                else:
                    a=2*math.pi*i/16;s['p']=1700.*np.array([math.cos(a),math.sin(a)])
            solver=OmniVariant(AuditPort(backend),3,ring_radius=radius,
                               ring_count=ring_count,guard_initial=True)
            result=solver.run()
            self.assertTrue(solver.ring_activated,ring_count)
            self.assertEqual(len(solver.cleared),16,ring_count)
            # Every site visited exactly once (no duplicate centre scan).
            self.assertEqual(sorted(solver.visited),list(range(len(solver.stations))),ring_count)

    def test_known_skip_radius_only_skips_known_targets(self):
        solver=OmniVariant(None,3,ring_radius=1123.,guard_initial=True,close_known=True,skip_known_radius=1200.)
        self.assertFalse(solver.skip_station_measurement(7,np.zeros(2)))
        solver.deferred[7]=1
        with patch.object(solver,'region',return_value=(None,np.array([3000.,0.]),100.)):
            self.assertTrue(solver.skip_station_measurement(7,np.zeros(2)))
        with patch.object(solver,'region',return_value=(None,np.array([300.,0.]),100.)):
            self.assertFalse(solver.skip_station_measurement(7,np.zeros(2)))

    def test_known_skip_radius_still_clears_every_source(self):
        backend=LocalBackend(3430093,3)
        solver=OmniVariant(AuditPort(backend),3,ring_radius=1123.,guard_initial=True,
                           close_known=True,skip_known_radius=1200.)
        result=solver.run()
        self.assertEqual(len(solver.cleared),len(backend.sources))
        self.assertEqual(set(solver.visited),set(range(len(solver.stations))))

    def test_finish_step_only_after_discovery(self):
        for count in [10,16]:
            old=LocalBackend(3100420,4,n=count);new=LocalBackend(3100420,4,n=count)
            class Capture(FinishStep):
                switch_index=None
                def locate(self,c):
                    if self.switch_index is None and (self.discovery_closed or not self.pending_stations):
                        self.switch_index=len(new.trace)
                    return super().locate(c)
            JointSearchSolver(AuditPort(old),4).run();solver=Capture(AuditPort(new),4);solver.run()
            self.assertEqual(len(solver.cleared),count)
            end=solver.switch_index if solver.switch_index is not None else len(new.trace)
            self.assertEqual(old.trace[:end],new.trace[:end])


if __name__=='__main__':unittest.main()
