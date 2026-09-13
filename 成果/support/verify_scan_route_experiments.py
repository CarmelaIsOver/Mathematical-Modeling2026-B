"""Reproduce the frozen Q3 layout comparison without changing live code."""
import argparse,base64,hashlib,json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--runs',type=int,default=200);p.add_argument('--seed',type=int,default=4400000)
    a=p.parse_args()
    if a.runs<1:p.error('--runs must be positive')
    fixtures=json.loads((ROOT/'results/scan_route/confirmation_q3_sources.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='scan-route-') as temp:
        folder=Path(temp).resolve()
        for name,item in fixtures.items():
            path=(folder/name).resolve();data=base64.b64decode(item['bytes_base64'])
            if folder not in path.parents:raise ValueError('Invalid fixture path')
            if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Invalid fixture digest')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        subprocess.run([sys.executable,str(folder/'tmp/scan_route_experiment.py'),'--problem','3','--start',str(a.seed),
            '--count',str(a.runs),'--modes','baseline','hex1125','--tag','reproduction'],cwd=folder,check=True)
        out=ROOT/'results/scan_route/reproduction';out.mkdir(parents=True,exist_ok=True)
        for suffix in ('.json','_cases.json'):
            name='reproduction_q3'+suffix
            (out/name).write_bytes((folder/'成果/support/results/scan_route'/name).read_bytes())
    print('Frozen Q3 layout comparison saved.')

if __name__=='__main__':main()
