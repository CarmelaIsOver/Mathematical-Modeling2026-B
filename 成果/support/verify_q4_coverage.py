"""Reproduce the frozen Q4 coverage experiment without simulator connections."""
import argparse,base64,hashlib,json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--runs',type=int,default=200);p.add_argument('--seed',type=int,default=2600000)
    a=p.parse_args()
    if a.runs<1:p.error('--runs must be positive')
    fixture=json.loads((ROOT/'results/q4_adaptive/frozen_sources.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='q4-coverage-') as temp:
        folder=Path(temp)
        for name,item in fixture.items():
            data=base64.b64decode(item['bytes_base64']);path=(folder/name).resolve()
            if folder.resolve() not in path.parents:raise ValueError('Invalid fixture path')
            if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Invalid fixture digest')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        subprocess.run([sys.executable,str(folder/'tmp/q4_adaptive_experiment.py'),'--start',str(a.seed),
            '--count',str(a.runs),'--modes','baseline','capped','--tag','reproduction'],check=True,cwd=folder)
        out=ROOT/'results/q4_adaptive/reproduction';out.mkdir(parents=True,exist_ok=True)
        for name in ('reproduction.csv','reproduction.json'):
            (out/name).write_bytes((folder/'成果/support/results/q4_adaptive'/name).read_bytes())
    print('Frozen Q4 coverage reproduction saved.')

if __name__=='__main__':main()
