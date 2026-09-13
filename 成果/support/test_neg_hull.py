"""Targeted inclusion tests for the teammate negative-range relaxation."""
import sys, unittest
sys.path.insert(0,'.'); sys.path.insert(0,'research/iterative_speed')
import numpy as np
from localization_service import outside_disk_hull

class InclusionTests(unittest.TestCase):
    def _kept(self, poly, q, samples):
        out = outside_disk_hull(np.asarray(poly,float), np.asarray(q,float))
        return out, np.all([self._inside(out, g) for g in samples])
    @staticmethod
    def _inside(poly, g):
        # inside-or-on a convex polygon (all cross products the same sign)
        n=len(poly); pos=neg=False
        for i in range(n):
            a,b=poly[i],poly[(i+1)%n]
            c=(b[0]-a[0])*(g[1]-a[1])-(b[1]-a[1])*(g[0]-a[0])
            if c>1e-9: pos=True
            elif c<-1e-9: neg=True
            if pos and neg: return False
        return True

    def test_no_feasible_sample_is_ever_removed(self):
        rng=np.random.default_rng(7)
        poly=np.array([[-1800.,-1800.],[1800.,-1800.],[1800.,1800.],[-1800.,1800.]])
        for _ in range(40):
            q=rng.uniform(-1800,1800,2)
            g=rng.uniform(-1800,1800,2)
            if np.linalg.norm(g-q) <= 1000.0:      # only provably infeasible points may go
                continue
            out=outside_disk_hull(poly,q)
            self.assertTrue(self._inside(out,g), f'feasible point removed: q={q} g={g}')

    def test_edge_circle_tangent_is_kept(self):
        poly=np.array([[-1500.,900.],[-1000.,900.],[-1000.,1100.],[-1500.,1100.]])
        q=np.array([-2500.,1000.])                   # disk tangent to the right edge x=-1000
        out=outside_disk_hull(poly,q)
        self.assertTrue(len(out)>=3)
        for g in ([-1000.,900.],[-1000.,1100.],[-1000.,1000.]):
            self.assertTrue(self._inside(out,np.asarray(g,float)))

    def test_thin_sliver_and_degenerate_polygon(self):
        thin=np.array([[0.,0.],[2000.,0.],[2000.,1.],[0.,1.]])
        q=np.array([-900.,0.5])                      # disk covers the left half
        out=outside_disk_hull(thin,q)
        self.assertTrue(len(out)>=3)
        self.assertTrue(self._inside(out,np.array([1500.,0.5])), 'far part of the sliver kept')
        deg=np.array([[0.,0.],[1000.,0.],[2000.,0.]])  # collinear
        try:
            out2=outside_disk_hull(deg,np.array([-500.,0.]))
            self.assertTrue(len(out2)>=1)
        except RuntimeError:
            pass                                      # contradiction may legitimately raise

    def test_all_vertices_inside_disk_raises(self):
        poly=np.array([[-100.,-100.],[100.,-100.],[100.,100.],[-100.,100.]])
        with self.assertRaises(RuntimeError):
            outside_disk_hull(poly,np.array([0.,0.]))

    def test_all_vertices_outside_returns_polygon(self):
        poly=np.array([[2000.,2000.],[3000.,2000.],[3000.,3000.]])
        out=outside_disk_hull(poly,np.array([0.,0.]))
        self.assertEqual(out.shape,poly.shape)

    def test_sequential_exclusions_stay_conservative(self):
        poly=np.array([[-1800.,-1800.],[1800.,-1800.],[1800.,1800.],[-1800.,1800.]])
        negs=[np.array([-1200.,0.]),np.array([1200.,0.])]
        cur=poly
        for q in negs: cur=outside_disk_hull(cur,q)
        for g in ([0.,1700.],[0.,-1700.],[1700.,0.],[-1700.,0.]):
            g=np.asarray(g,float)
            if all(np.linalg.norm(g-q)>1000.0 for q in negs):
                self.assertTrue(self._inside(cur,g), f'feasible point removed after 2 exclusions: {g}')

if __name__=='__main__': unittest.main()
