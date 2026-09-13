"""Fusion Q3 parity and unchanged Q4 source/trace/entry checks."""
import contextlib,hashlib,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from backend import LocalBackend
from audit import AuditPort
from omni_search import OmniSearchSolver
from joint_search import JointSearchSolver
import run as entry

ROOT=Path(__file__).resolve().parent
REFERENCE=json.loads((ROOT/'results/validation/q3_replacement/before.json').read_text())
def backend(f):
    b=LocalBackend(f['seed'],f['problem'],radius=1000 if f['seed']%3==0 else None)
    if f['problem']==3 and f['seed']%3==0:
        for i,x in enumerate(b.sources.values()):
            a=2*np.pi*i/len(b.sources);x['p']=1800*np.array([np.cos(a),np.sin(a)])
    return b

class ReplacementTests(unittest.TestCase):
    def test_q4_dependencies_unchanged(self):
        for name,digest in REFERENCE['unchanged_q4_dependencies'].items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest,name)

    def test_q3_copied_source_matches_fusion(self):
        for name,digest in REFERENCE['fusion_source'].items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest,name)

    def test_full_traces_match_fusion_q3_and_original_q4(self):
        for f in REFERENCE['fixtures']:
            b=backend(f);p=AuditPort(b);ctor=OmniSearchSolver if f['problem']==3 else JointSearchSolver
            r=ctor(p,f['problem'],**f['kwargs']).run()
            digest=hashlib.sha256(json.dumps(b.trace,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            self.assertEqual(digest,f['trace_sha256'],f);self.assertTrue(p.exited)
            self.assertEqual(r['mean_time_s'],f['mean_time_s']);self.assertEqual(r['cleared'],len(b.sources))

    def test_default_entry_uses_fusion_q3_and_unchanged_q4(self):
        for problem in (3,4):
            for seed in (4800000,4800001):
                f=next(x for x in REFERENCE['fixtures'] if x['problem']==problem and x['seed']==seed)
                b=backend(f)
                with tempfile.TemporaryDirectory() as folder:
                    with patch.object(sys,'argv',['run.py','--mode','official','--problem',str(problem),
                        '--robot-id','TEST_PLACEHOLDER','--output',folder]),patch.object(entry,'HTTPBackend',return_value=b),contextlib.redirect_stdout(io.StringIO()):
                        entry.main()
                    r=json.loads(next(Path(folder).glob('client_*.json')).read_text())
                    self.assertEqual(r['mean_time_s'],f['mean_time_s']);self.assertTrue(r['complete'] and r['normal_exit'])
                    digest=hashlib.sha256(json.dumps(b.trace,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                    self.assertEqual(digest,f['trace_sha256'])
                    if problem==4:
                        self.assertEqual((r['coverage_layout'],r['service_policy']),('rings','adaptive'))
                        self.assertNotIn('q3_ring_guard',r)
                    else:
                        self.assertEqual((r['q3_ring_guard'],r['q3_probe_radius']),('aggressive',60.))

if __name__=='__main__':unittest.main()
