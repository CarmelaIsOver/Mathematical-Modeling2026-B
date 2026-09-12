"""Reproduce the frozen target-400 experiment without touching live log files."""
import argparse,base64,hashlib,json,subprocess,sys,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def materialize(folder):
    fixtures=json.loads((ROOT/'results/target400/frozen_sources.json').read_text(encoding='utf-8'))
    for name,item in fixtures.items():
        data=base64.b64decode(item['bytes_base64'])
        if hashlib.sha256(data).hexdigest()!=item['sha256']:
            raise ValueError('Frozen source checksum mismatch: '+name)
        path=(folder/name).resolve()
        if folder.resolve() not in path.parents:raise ValueError('Invalid fixture path')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--runs',type=int,default=200)
    ap.add_argument('--seed',type=int,default=1900000)
    a=ap.parse_args()
    if a.runs<1:ap.error('--runs must be positive')
    with tempfile.TemporaryDirectory(prefix='bearing-reproduce-') as temp:
        folder=Path(temp);materialize(folder)
        subprocess.run([sys.executable,str(folder/'tmp/target400_experiment.py'),
            '--start',str(a.seed),'--count',str(a.runs),'--modes','original','reference','multitour',
            '--tag','reproduction'],check=True,cwd=folder)
        out=ROOT/'results/target400/reproduction';out.mkdir(parents=True,exist_ok=True)
        for name in ('reproduction.csv','reproduction.json'):
            (out/name).write_bytes((folder/'成果/support/results/target400'/name).read_bytes())
    print('Frozen reproduction saved under results/target400/reproduction')


if __name__=='__main__':main()
