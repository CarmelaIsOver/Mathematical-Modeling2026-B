"""Reproduce the comparison in a temporary directory, not the live controller."""
import argparse,base64,json,subprocess,sys,tempfile,shutil
from pathlib import Path


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--problem',type=int,choices=[3,4],required=True)
    ap.add_argument('--count',type=int,default=200)
    ap.add_argument('--output',type=Path,default=Path('results/reproduction'))
    a=ap.parse_args()
    if not 1<=a.count<=200:ap.error('--count must be between 1 and 200')
    root=Path(__file__).resolve().parent/'results/optimization'
    fixture=json.loads((root/'experiment_sources.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='source-comparison-') as tmp:
        path=Path(tmp)
        for name,data in fixture['files'].items():
            if Path(name).name!=name or not name.endswith('.py'):raise ValueError('Invalid fixture path')
            (path/name).write_bytes(base64.b64decode(data['bytes_base64']))
        shutil.copy2(root/'protocol.json',path/'protocol.json')
        mode='combined' if a.problem==3 else 'route'
        subprocess.run([sys.executable,'evaluate.py','--problem',str(a.problem),'--start','820000',
                        '--count',str(a.count),'--modes','original','reference',mode,'--tag','reproduction'],cwd=path,check=True)
        a.output.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path/f'results/reproduction/q{a.problem}.csv',a.output/f'q{a.problem}.csv')

if __name__=='__main__':main()
