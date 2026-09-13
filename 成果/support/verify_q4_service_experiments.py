"""Reproduce frozen Q4 service/routing ablations using synthetic scenes only."""
import argparse,base64,hashlib,json,subprocess,sys,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--runs',type=int,default=200)
    p.add_argument('--seed',type=int,default=3300000)
    a=p.parse_args()
    if a.runs<1:p.error('--runs must be positive')
    fixture=json.loads((ROOT/'results/q4_service/holdout_sources.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='q4-service-') as temp:
        folder=Path(temp).resolve()
        for name,item in fixture.items():
            data=base64.b64decode(item['bytes_base64']);path=(folder/name).resolve()
            if folder not in path.parents:raise ValueError('Invalid fixture path')
            if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Invalid fixture digest')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        subprocess.run([sys.executable,str(folder/'tmp/q4_service_experiment.py'),
            '--start',str(a.seed),'--count',str(a.runs),'--modes','baseline','rings','step_rank_rings',
            '--tag','reproduction'],check=True,cwd=folder)
        out=ROOT/'results/q4_service/reproduction';out.mkdir(parents=True,exist_ok=True)
        for name in ('reproduction_cases.json','reproduction.json'):
            (out/name).write_bytes((folder/'成果/support/results/q4_service'/name).read_bytes())
    print('Frozen Q4 service reproduction saved.')

if __name__=='__main__':main()
