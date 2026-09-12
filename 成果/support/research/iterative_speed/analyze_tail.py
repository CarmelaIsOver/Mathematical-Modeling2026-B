"""Paired tail analysis for a study round, saved as a reproducible artifact.

Writes ``tail_analysis.json`` into the round directory with per-arm paired ratios and
the offsets of the worst and typical seeds, so every tail number quoted in the ledger
(including the >10% degradation counts that ``study.summarize`` does not emit) has a
verifiable source.

Usage: python analyze_tail.py <round_dir_name> <control_variant> <arm> [<arm> ...]
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent


def analyze(round_name, control, arms):
    folder = ROOT / 'results' / round_name
    rows = [json.loads(l) for l in (folder / 'metrics.jsonl').open(encoding='utf-8')]
    ctl = {r['seed']: r for r in rows if r['variant'] == control}
    out = {'round': round_name, 'control': control, 'arms': {}}
    for arm in arms:
        g = [r for r in rows if r['variant'] == arm]
        d = np.array([r['score_time_s'] / ctl[r['seed']]['score_time_s'] - 1 for r in g])
        seeds = [r['seed'] for r in g]
        order = np.argsort(d)
        out['arms'][arm] = {
            'n': len(g),
            'mean_of_ratios_delta_pct': round(float(100 * d.mean()), 3),
            'median_of_ratios_delta_pct': round(float(100 * np.median(d)), 3),
            'ratio_of_means_delta_pct': round(float(100 * (np.mean([r['score_time_s'] for r in g])
                                                          / np.mean([ctl[r['seed']]['score_time_s'] for r in g]) - 1)), 3),
            'slower5': int((d > .05).sum()),
            'slower10': int((d > .10).sum()),
            'better5': int((d < -.05).sum()),
            'failures': int(sum(not r['full_clear'] for r in g)),
            'worst_seed': int(seeds[order[-1]]),
            'worst_delta_pct': round(float(100 * d[order[-1]]), 3),
            'best_seed': int(seeds[order[0]]),
            'typical_seed': int(seeds[order[len(order) // 2]]),
            'typical_delta_pct': round(float(100 * d[order[len(order) // 2]]), 3),
            'worst_percentile': {'p95_delta_pct': round(float(100 * np.percentile(d, 95)), 3),
                                 'p99_delta_pct': round(float(100 * np.percentile(d, 99)), 3),
                                 'cvar95_delta_pct': round(float(100 * np.sort(d)[-max(1, int(np.ceil(.05 * len(d)))):].mean()), 3)},
        }
    (folder / 'tail_analysis.json').write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    return out


def main():
    round_name, control, *arms = sys.argv[1:]
    print(json.dumps(analyze(round_name, control, arms), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
