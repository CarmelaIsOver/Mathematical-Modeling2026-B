"""Separate mechanism trigger rate from realised gain, per round and per arm.

Writes ``trigger_analysis.json`` next to the round data: raw trigger counters, the
fraction of scenes where the mechanism actually fired, and the paired delta split by
"fired" vs "did not fire". Triggered-but-no-gain and never-triggered are different
findings and must not be conflated.

Usage: python analyze_trigger.py <round> <control> <counter_key> <arm> [<counter_key> ...]
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent


def analyze(round_name, control, specs):
    folder = ROOT / 'results' / round_name
    rows = [json.loads(l) for l in (folder / 'metrics.jsonl').open(encoding='utf-8')]
    ctl = {r['seed']: r for r in rows if r['variant'] == control}
    out = {'round': round_name, 'control': control, 'arms': {}}
    for arm, key in specs:
        g = [r for r in rows if r['variant'] == arm]
        if not g:
            continue
        delta = np.array([100 * (r['score_time_s'] / ctl[r['seed']]['score_time_s'] - 1) for r in g])
        trig = np.array([r.get(key, 0) for r in g], float)
        fired = trig > 0
        out['arms'][arm] = {
            'counter': key,
            'n_scenes': len(g),
            'total_triggers': int(trig.sum()),
            'triggers_per_scene': round(float(trig.mean()), 2),
            'scenes_with_trigger': int(fired.sum()),
            'trigger_rate': round(float(fired.mean()), 3),
            'mean_delta_pct_all': round(float(delta.mean()), 3),
            'mean_delta_pct_fired': (round(float(delta[fired].mean()), 3) if fired.any() else None),
            'mean_delta_pct_not_fired': (round(float(delta[~fired].mean()), 3) if (~fired).any() else None),
            'worst_delta_pct_fired': (round(float(delta[fired].max()), 3) if fired.any() else None),
        }
    (folder / 'trigger_analysis.json').write_text(json.dumps(out, indent=2, ensure_ascii=False),
                                                  encoding='utf-8')
    return out


def main():
    round_name, control = sys.argv[1], sys.argv[2]
    rest = sys.argv[3:]
    specs = list(zip(rest[1::2], rest[0::2]))   # key arm key arm ...
    print(json.dumps(analyze(round_name, control, specs), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
