"""Round-3 verification artifacts: probe statistics and production parity verdicts.

Writes machine-checkable JSON next to the round data so claims in the ledger/report
can be reproduced without reading per-scene rows.
"""
import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'results' / 'r37_round3_verification'


def load_metrics(round_name):
    rows = [json.loads(l) for l in (ROOT / 'results' / round_name / 'metrics.jsonl').open(encoding='utf-8')]
    return rows


def probe_stats():
    rows = load_metrics('r32_q3_probe200')
    base = {r['seed']: r for r in rows if r['variant'] == 'baseline'}
    ctl = {r['seed']: r for r in rows if r['variant'] == 'guard1123_close_skip12'}
    out = {'round': 'r32_q3_probe200', 'n': len(ctl), 'control_mean': float(np.mean([r['score_time_s'] for r in ctl.values()])), 'arms': {}}
    for variant in ('skip12_probe40', 'skip12_probe60'):
        g = [r for r in rows if r['variant'] == variant]
        t = np.array([r['score_time_s'] for r in g])
        rt_base = np.array([r['score_time_s'] / base[r['seed']]['score_time_s'] for r in g])
        rt_ctl = np.array([r['score_time_s'] / ctl[r['seed']]['score_time_s'] for r in g])
        tail = np.sort(rt_ctl)[-int(np.ceil(.05 * len(rt_ctl))):]
        attempts = sum(r['extra_probe_attempts'] for r in g)
        out['arms'][variant] = {
            'mean_s_per_source': round(float(t.mean()), 3),
            'mean_of_ratios_vs_control': round(float(rt_ctl.mean()), 5),
            'gain_mean_of_ratios_pct': round(float(100 * (1 - rt_ctl.mean())), 3),
            'gain_ratio_of_means_pct': round(float(100 * (1 - t.mean() / out['control_mean'])), 3),
            'median_ratio': round(float(np.median(rt_ctl)), 4),
            'p95_ratio_higher': round(float(np.percentile(rt_ctl, 95, method='higher')), 4),
            'cvar95_ratio': round(float(tail.mean()), 4),
            'worst_ratio': round(float(rt_ctl.max()), 4),
            'worst_absolute_s': round(float(t.max()), 2),
            'scenes_over_5pct': int((rt_ctl > 1.05).sum()),
            'failures': int(sum(not r['full_clear'] for r in g)),
            'mean_measures': round(float(np.mean([r['measure'] for r in g])), 2),
            'probe_attempts': attempts,
            'probe_successes': int(sum(r['extra_probe_successes'] for r in g)),
            'probe_success_rate': round(sum(r['extra_probe_successes'] for r in g) / max(1, attempts), 4),
            'mean_of_ratios_vs_baseline': round(float(rt_base.mean()), 5),
        }
    return out


def production_parity():
    ref_rows = load_metrics('r32_q3_probe200')
    ref = {(r['seed'], r['variant']): r for r in ref_rows}
    fields = [('mean_time_s', 'score_time_s'), ('measure', 'measure'), ('cleared', 'cleared'),
              ('virtual_time_s', 'virtual_time_s'), ('extra_probe_attempts', 'extra_probe_attempts'),
              ('extra_probe_successes', 'extra_probe_successes'), ('fallback', 'fallback'),
              ('failed_clear', 'failed_clear')]
    out = {'round': 'r33_q3_probe_prod', 'seeds': '3484000-3484019', 'arms': {}}
    total = mismatch = 0
    for arm, variant in (('arc40', 'skip12_probe40'), ('arc60', 'skip12_probe60')):
        with (ROOT / 'results' / 'r33_q3_probe_prod' / arm / 'local_q3.csv').open(encoding='utf-8-sig', newline='') as f:
            prod = {int(r['seed']): r for r in csv.DictReader(f)}
        bad = []
        for seed in range(3484000, 3484020):
            for pk, rk in fields:
                total += 1
                if abs(float(prod[seed][pk]) - float(ref[(seed, variant)][rk])) > 1e-9:
                    bad.append({'seed': seed, 'field': pk, 'prod': prod[seed][pk], 'research': ref[(seed, variant)][rk]})
                    mismatch += 1
        out['arms'][arm] = {'variant': variant, 'seeds_compared': 20, 'fields_per_seed': len(fields),
                            'mismatches': len(bad), 'identical': not bad, 'diffs': bad[:5]}
    out['fields_compared'] = total
    out['mismatches'] = mismatch
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {'probe_stats': probe_stats(), 'production_parity': production_parity()}
    (OUT / 'verification.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
