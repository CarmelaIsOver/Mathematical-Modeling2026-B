"""Reproduce frozen paired Q3 experiments without connecting to the simulator."""
import argparse,base64,hashlib,json,subprocess,sys,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--runs',type=int,default=200)
    ap.add_argument('--seed',type=int,default=2300000);a=ap.parse_args()
    if a.runs<1:ap.error('--runs must be positive')
    fixture=json.loads((ROOT/'results/q3_scheduling/frozen_sources.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='q3-schedule-') as temp:
        folder=Path(temp)
        for name,item in fixture.items():
            data=base64.b64decode(item['bytes_base64'])
            if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Invalid frozen source hash')
            path=(folder/name).resolve()
            if folder.resolve() not in path.parents:raise ValueError('Invalid fixture path')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        subprocess.run([sys.executable,str(folder/'tmp/q3_schedule_experiment.py'),
            '--start',str(a.seed),'--count',str(a.runs),'--modes','baseline','tour_select','--tag','reproduction'],check=True,cwd=folder)
        out=ROOT/'results/q3_scheduling/reproduction';out.mkdir(parents=True,exist_ok=True)
        for name in ['reproduction.json','reproduction.csv']:
            (out/name).write_bytes((folder/'成果/support/results/q3_scheduling'/name).read_bytes())
    print('Frozen Q3 results saved under results/q3_scheduling/reproduction')


if __name__=='__main__':main()
