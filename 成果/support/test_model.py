import math
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
import numpy as np
from geometry import (unit,feasible,enclosing_circle,diameter,region_from_bearings,
                      search_stations,optical_cover)
from backend import LocalBackend,HTTPBackend
from solver import Solver

class ModelTests(unittest.TestCase):
    def test_attachment_timing(self):
        b=LocalBackend(1,3)
        b.sources={}
        b.enter()
        b.action('/measure',[300,400],1)
        b.action('/measure',[300,400],2)
        b.action('/clear',[300,0],3)
        b.action('/measure',[300,0],2)
        self.assertEqual(b.virtual_time,199)
        self.assertEqual(b.channel,2)

    def test_equilateral(self):
        p=np.array([[0.,0.],[40.,0.],[20.,20*math.sqrt(3)]])
        self.assertAlmostEqual(diameter(p)[0],40)
        self.assertAlmostEqual(enclosing_circle(p)[1],40/math.sqrt(3))
        self.assertGreater(enclosing_circle(p)[1],20)

    def test_bounded_empty_unbounded(self):
        self.assertEqual(region_from_bearings([([0,0],0)])['status'],'unbounded')
        self.assertEqual(region_from_bearings([([0,0],180),([1,0],0)])['status'],'empty')
        r=region_from_bearings([([0,0],45),([1000,0],135)])
        self.assertEqual(r['status'],'bounded')
        self.assertTrue(0<r['diameter']<100)

    def test_rounding_wrap_and_region_contains_truth(self):
        g=np.array([1200.,-.01])
        observations=[]
        for p,e in [(np.array([0.,0.]),1.005),(np.array([1000.,300.]),-1.005)]:
            d=g-p
            theta=(math.degrees(math.atan2(d[1],d[0]))+e)%360
            observations.append((p,theta))
        poly=feasible(observations)
        for a,b in zip(poly,np.roll(poly,-1,axis=0)):
            u=b-a;v=g-a
            self.assertGreaterEqual(float(u[0]*v[1]-u[1]*v[0]),-1e-5)

    def test_repeated_position_error_is_fixed(self):
        b=LocalBackend(3,3)
        self.assertEqual(b.error([10.,20.],1),b.error([10.,20.],1))

    def test_q3_geometric_coverage(self):
        s=search_stations(3)
        for r in np.linspace(0,1800,61):
            for angle in np.linspace(0,360,361):
                self.assertLessEqual(np.min(np.linalg.norm(s-r*unit(angle),axis=1)),1000+1e-6)

    def test_q4_halfplane_coverage_boundary_and_interior(self):
        s=search_stations(4)
        rng=np.random.default_rng(10)
        points=[1800*unit(a) for a in np.arange(0,360,3.)]
        points.extend(1800*math.sqrt(rng.random())*unit(rng.uniform(0,360)) for _ in range(400))
        for p in points:
            delta=s-p
            nearby=delta[np.linalg.norm(delta,axis=1)<=1000+1e-6]
            for angle in range(0,360,5):
                self.assertTrue(np.any(nearby@unit(angle)>=-1e-6))

    def test_optical_cover(self):
        poly=feasible([(np.array([0.,0.]),359.99)])
        points=optical_cover(poly,359.99)
        rng=np.random.default_rng(1)
        for _ in range(1000):
            weights=rng.random(len(poly));weights/=weights.sum()
            p=weights@poly
            self.assertLessEqual(np.min(np.linalg.norm(points-p,axis=1)),20.)

    def test_clear_independent_of_beam(self):
        b=LocalBackend(3,4)
        b.sources={1:dict(p=np.array([0.,0.]),radius=1000.,direction=0.,alive=True)}
        self.assertEqual(b.action('/measure',[-10,0],1)['measure_result'],'no_signal')
        self.assertEqual(b.action('/clear',[-10,0],1)['clear_result'],'success')
        self.assertEqual(b.action('/clear',[-10,0],1)['clear_result'],'no_target_in_range')

    def test_optical_fallback_forced(self):
        b=LocalBackend(11,4,all_directional=True,n=10,radius=1000.)
        result=Solver(b,4,max_refine=0).run()
        self.assertEqual(result['cleared'],10)
        self.assertGreater(result['fallback'],0)

    def test_http_retry_idempotency_and_rejection(self):
        class FakeOpener:
            def __init__(self):
                self.requests=[]
            def open(self,request,timeout):
                self.requests.append(request)
                if len(self.requests)==1:
                    raise urllib.error.URLError('response lost after execution')
                return io.BytesIO(json.dumps({'accepted':True,'virtual_time_s':5}).encode())
        with tempfile.TemporaryDirectory() as tmp:
            api=HTTPBackend('TEST','http://127.0.0.1:2026',Path(tmp)/'log.jsonl')
            fake=FakeOpener();api.opener=fake
            with patch('backend.time.sleep'):
                api.action('/measure',[0,0],1)
            self.assertEqual(fake.requests[0].data,fake.requests[1].data)
            self.assertEqual(fake.requests[0].full_url,fake.requests[1].full_url)
            self.assertEqual(api.virtual_time,5)
            api.log.close()

if __name__=='__main__':
    unittest.main(verbosity=2)
