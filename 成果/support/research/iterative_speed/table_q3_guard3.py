"""Unified Q3 ring-guard three-arm table from the existing r25 fixed-200 run.

Reads results/r25_q3_fixed200/{summary.json,metrics.jsonl} (no rerun) and prints the
single comparison table used in OPTIMIZATION_LEDGER.md chapter 0. Aggregates only:
individual per-seed rows are not printed.
"""
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
R25 = ROOT / 'results' / 'r25_q3_fixed200'
ARMS = [('baseline', 'off'), ('guard1123_close_skip12', 'aggressive'),
        ('guard1123_close_skip12_k6', 'conservative')]
HDR = ('arm', 'n', 's/source', 'gain', 'median', 'P90', 'P95', 'P99', 'CVaR95',
       'worst_abs', 'worst_ratio', '>5%', 'fail', 'measure')


def pct(vals, q):
    import numpy as np
    return float(np.percentile(vals, q))


def main():
    rows = [json.loads(line) for line in (R25 / 'metrics.jsonl').open(encoding='utf-8')]
    base = {r['seed']: r for r in rows if r['variant'] == 'baseline'}
    summary = json.loads((R25 / 'summary.json').read_text(encoding='utf-8'))
    print(' | '.join(HDR))
    print(' | '.join('---' if i == 0 else '---:' for i in range(len(HDR))))
    for variant, label in ARMS:
        group = [r for r in rows if r['variant'] == variant]
        times = [r['score_time_s'] for r in group]
        ratios = sorted(r['score_time_s'] / base[r['seed']]['score_time_s'] for r in group)
        s = summary[variant]
        vals = [label,
                str(len(group)),
                f"{s['mean']:.2f}",
                '—' if variant == 'baseline' else f"{100 * s['gain']:.2f}%",
                f'{statistics.median(ratios):.4f}',
                f'{pct(times, 90):.2f}',
                f"{s['p95']:.2f}",
                f"{s['p99']:.2f}",
                f"{s['cvar95']:.2f}",
                f"{s['worst']:.2f}",
                f"{s['worst_ratio']:.4f}",
                str(s['slower5']),
                str(s['failures']),
                f"{s['measure']:.2f}"]
        print(' | '.join(vals))
    print(f"\nworst-ratio seed (both guarded arms): {summary['guard1123_close_skip12']['worst_seed']}")
    for variant, _ in ARMS[1:]:
        s = summary[variant]
        print(f"{variant}: wins={s['wins']}/{s['n']}  phases={ {k: round(v) for k, v in s['phases'].items()} }")


if __name__ == '__main__':
    main()
