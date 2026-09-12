"""Reproduce the frozen paper-inspired offline comparison in a temporary directory."""
import argparse, base64, hashlib, json, shutil, subprocess, sys, tempfile
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--problem',type=int,choices=(3,4),required=True)
    parser.add_argument('--count',type=int,default=200)
    parser.add_argument('--output',type=Path,default=Path('results/paper_reproduction'))
    args=parser.parse_args()
    if not 1<=args.count<=200:parser.error('--count must be between 1 and 200')
    fixture=Path(__file__).resolve().parent/'results/paper_localization/frozen_sources.json'
    sources=json.loads(fixture.read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='paper-localization-') as folder:
        root=Path(folder).resolve()
        for name,record in sources.items():
            path=(root/name).resolve()
            if not path.is_relative_to(root) or path.suffix!='.py':
                raise ValueError('Invalid frozen source path')
            content=base64.b64decode(record['bytes_base64'])
            if hashlib.sha256(content).hexdigest()!=record['sha256']:
                raise ValueError('Frozen source checksum mismatch')
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(content)
        (root/'成果/support/results').mkdir(exist_ok=True)
        subprocess.run([sys.executable,str(root/'tmp/paper_experiment.py'),
            '--problem',str(args.problem),'--start','940000','--count',str(args.count),
            '--tag','reproduction'],cwd=root,check=True)
        args.output.mkdir(parents=True,exist_ok=True)
        for suffix in ('csv','json'):
            source=root/f'成果/support/results/paper_localization/reproduction_q{args.problem}.{suffix}'
            shutil.copy2(source,args.output/source.name)


if __name__=='__main__':main()
