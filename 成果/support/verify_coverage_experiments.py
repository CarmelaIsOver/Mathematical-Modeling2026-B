"""Reproduce frozen coverage comparisons without contacting the simulator."""
import argparse,base64,hashlib,json,shutil,subprocess,sys,tempfile
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layout',choices=['compressed','shifted'],default='compressed')
    parser.add_argument('--localization',choices=['paper','standard'],default='paper')
    parser.add_argument('--count',type=int,default=200)
    parser.add_argument('--output',type=Path,default=Path('results/coverage_reproduction'))
    args=parser.parse_args()
    if not 1<=args.count<=200:parser.error('--count must be between 1 and 200')
    data=Path(__file__).resolve().parent/'results/coverage_optimization'
    filename='compressed_sources.json' if args.layout=='compressed' else 'frozen_sources.json'
    fixture=json.loads((data/filename).read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='coverage-comparison-') as directory:
        root=Path(directory).resolve()
        for name,record in fixture.items():
            path=(root/name).resolve()
            if not path.is_relative_to(root) or path.suffix!='.py':raise ValueError('Invalid fixture path')
            content=base64.b64decode(record['bytes_base64'])
            if hashlib.sha256(content).hexdigest()!=record['sha256']:raise ValueError('Frozen source changed')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
        start=1500000 if args.layout=='compressed' else 1200000
        tag=f'reproduction_{args.layout}_{args.localization}'
        subprocess.run([sys.executable,str(root/'tmp/coverage_experiment.py'),
            '--start',str(start),'--count',str(args.count),'--layouts','centered',args.layout,
            '--localization',args.localization,'--tag',tag],cwd=root,check=True)
        args.output.mkdir(parents=True,exist_ok=True)
        for suffix in ('csv','json'):
            source=root/f'成果/support/results/coverage_optimization/{tag}.{suffix}'
            shutil.copy2(source,args.output/source.name)


if __name__=='__main__':main()
