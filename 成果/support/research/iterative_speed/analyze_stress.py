"""Aggregate the stress rounds with an EXPLICIT strong control per problem.

For every stress round the paired delta is computed against the declared strong
baseline only (Q3: skip12_probe60, Q4: baseline) - never against the old off arm.
Writes ``stress_analysis.json`` under results/r82_stress_summary/.
"""
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'results' / 'r82_stress_summary'
CONTROL = {3: 'skip12_probe60', 4: 'baseline'}
STRONG = {3: {'skip12_probe60'}, 4: {'baseline'}}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rounds = sorted(p for p in (ROOT / 'results').glob('r80*_stress*') if p.is_dir())
    out = {'control': {'Q3': 'skip12_probe60 (aggressive+probe60)', 'Q4': 'radial default'},
           'note': 'paired delta vs the strong baseline only; the off arm is never used',
           'rounds': {}}
    for folder in rounds:
        rows = [json.loads(l) for l in (folder / 'metrics.jsonl').open(encoding='utf-8')]
        if not rows:
            continue
        problem = rows[0]['problem']
        ctl_name = CONTROL[problem]
        ctl = {r['seed']: r for r in rows if r['variant'] == ctl_name}
        if not ctl:
            continue
        mode = json.loads((folder / 'protocol.json').read_text(encoding='utf-8'))['mode']
        for arm in sorted({r['variant'] for r in rows} - STRONG[problem]):
            g = [r for r in rows if r['variant'] == arm and r['seed'] in ctl]
            if not g:
                continue
            ratios = np.array([r['score_time_s'] / ctl[r['seed']]['score_time_s'] for r in g])
            times = np.array([r['score_time_s'] for r in g])
            ct = np.array([ctl[r['seed']]['score_time_s'] for r in g])
            moves = np.array([r['move_m'] for r in g])
            cmoves = np.array([ctl[r['seed']]['move_m'] for r in g])
            key = f'{folder.name}::{arm}'
            out['rounds'][key] = {
                'mode': mode, 'problem': problem, 'control_variant': ctl_name,
                'n': len(g),
                'mean_of_ratios_delta_pct': round(float(100 * (ratios.mean() - 1)), 3),
                'ratio_of_means_delta_pct': round(float(100 * (times.mean() / ct.mean() - 1)), 3),
                'worst_delta_pct': round(float(100 * (ratios.max() - 1)), 3),
                'worst_seed': int(g[int(ratios.argmax())]['seed']),
                'arm_move_m': round(float(moves.mean()), 1),
                'control_move_m': round(float(cmoves.mean()), 1),
                'failures': int(sum(not r['full_clear'] for r in g)),
            }
    agg = {}
    for key, v in out['rounds'].items():
        agg.setdefault(v['control_variant'] + '::' + v['mode'], []).append(v['mean_of_ratios_delta_pct'])
    out['per_mode_mean_pct'] = {k: round(float(np.mean(v)), 3) for k, v in sorted(agg.items())}
    (OUT / 'stress_analysis.json').write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    for key, v in out['rounds'].items():
        print(f"{key:<52} {v['control_variant']:<16} meanR={v['mean_of_ratios_delta_pct']:+7.2f}% "
              f"ratioMeans={v['ratio_of_means_delta_pct']:+7.2f}% worst={v['worst_seed']}({v['worst_delta_pct']:+.1f}%) "
              f"move={v['arm_move_m']:.0f}/{v['control_move_m']:.0f} fail={v['failures']}")


if __name__ == '__main__':
    main()
