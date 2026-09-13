"""Reproduce the exact frozen target-candidate experiments offline."""
import argparse,base64,hashlib,json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--problem',type=int,choices=[3,4],required=True)
    p.add_argument('--runs',type=int);p.add_argument('--seed',type=int);a=p.parse_args()
    count=a.runs if a.runs is not None else (300 if a.problem==3 else 200)
    seed=a.seed if a.seed is not None else (3800000 if a.problem==3 else 3600000)
    if count<1:p.error('--runs must be positive')
    name='final_holdout_q3_sources.json' if a.problem==3 else 'holdout_q4_sources.json'
    fixtures=json.loads((ROOT/'results/target_pair'/name).read_text(encoding='utf-8'))
    candidate='step_probe_tour_negative' if a.problem==3 else 'service'
    with tempfile.TemporaryDirectory(prefix='target-pair-') as temp:
        folder=Path(temp).resolve()
        for name,item in fixtures.items():
            data=base64.b64decode(item['bytes_base64']);path=(folder/name).resolve()
            if folder not in path.parents:raise ValueError('Invalid fixture path')
            if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Invalid fixture digest')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        subprocess.run([sys.executable,str(folder/'tmp/target_pair_experiment.py'),'--problem',str(a.problem),
            '--start',str(seed),'--count',str(count),'--modes','baseline',candidate,'--tag','reproduction'],
            check=True,cwd=folder)
        out=ROOT/'results/target_pair/reproduction';out.mkdir(parents=True,exist_ok=True)
        for suffix in ('.json','_cases.json'):
            name=f'reproduction_q{a.problem}{suffix}'
            (out/name).write_bytes((folder/'成果/support/results/target_pair'/name).read_bytes())
    print('Frozen target comparison saved.')

if __name__=='__main__':main()
