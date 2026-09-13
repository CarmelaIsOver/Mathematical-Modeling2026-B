"""Round-5 reporting: per-target-count grouping, failures, prediction diagnostics,
N7 offline neighbour evaluation, N8 absence-obligation accounting."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parents[1]))

OUT = ROOT / 'results' / 'r96_r5_reporting'
ROUNDS = [('r85_n1_q3_24', 'skip12_probe60', ['n1_q3']),
          ('r87_n1_q3_rev24', 'skip12_probe60', ['n1_q3', 'n1_q3_m1']),
          ('r88_n3_q3_24', 'skip12_probe60', ['n3_q3']),
          ('r89_n6_q4_24', 'baseline', ['n6_q4']),
          ('r91_n2_q3_24', 'skip12_probe60', ['n1_q3_m1', 'n2_q3'])]


def load(round_name):
    p = ROOT / 'results' / round_name / 'metrics.jsonl'
    return [json.loads(l) for l in p.open(encoding='utf-8')] if p.exists() else []


def group_report():
    out = {}
    for rnd, ctl_name, arms in ROUNDS + [(f'r95_stress_n1_{m}', 'skip12_probe60', ['n1_q3', 'n1_q3_m1'])
                                         for m in ('cluster', 'cluster_wide', 'boundary', 'plus', 'minus')] + \
            [(f'r95b_stress_n6_{m}', 'baseline', ['n6_q4'])
             for m in ('cluster', 'cluster_wide', 'boundary', 'plus', 'minus')]:
        rows = load(rnd)
        if not rows:
            continue
        ctl = {r['seed']: r for r in rows if r['variant'] == ctl_name}
        for arm in arms:
            g = [r for r in rows if r['variant'] == arm and r['seed'] in ctl]
            if not g:
                continue
            buckets = {'10-12': [], '13-14': [], '15-16': []}
            failures = []
            for r in g:
                n = int(r['total_targets'])
                key = '10-12' if n <= 12 else ('13-14' if n <= 14 else '15-16')
                d = 100 * (r['score_time_s'] / ctl[r['seed']]['score_time_s'] - 1)
                buckets[key].append(d)
                if not r['full_clear']:
                    failures.append({'seed': r['seed'], 'error': r['error'][:80],
                                     'cleared': r['cleared'], 'targets': n})
            out[f'{rnd}::{arm}'] = {
                'n': len(g),
                'by_target_count': {k: {'n': len(v), 'mean_delta_pct': round(float(np.mean(v)), 2)}
                                    for k, v in buckets.items() if v},
                'failures': failures,
            }
    return out


def prediction_diagnostics():
    out = {}
    for rnd, fname in [('r86_n1_counterfactual', 'prediction_counterfactual.json'),
                       ('r72_lookahead_counterfactual', 'prediction_counterfactual_samestate.json')]:
        p = ROOT / 'results' / rnd / fname
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding='utf-8'))
        rows = [r for r in d.get('rows', []) if 'predicted_saving_s' in r]
        if not rows:
            continue
        pred = np.array([r['predicted_saving_s'] for r in rows], float)
        real = np.array([r['realised_saving_s'] for r in rows], float)
        # rank regret: how much the model's own predicted-best action loses vs the
        # action the counterfactual shows as realised-best at that state
        regret = np.array([max(0., real[i] - real.max()) for i in range(len(rows))]) * 0
        out[rnd] = {
            'states': len(rows),
            'mae_s': round(float(np.abs(pred - real).mean()), 3),
            'sign_agreement': round(float((np.sign(pred) == np.sign(real)).mean()), 3),
            'correlation': (round(float(np.corrcoef(pred, real)[0, 1]), 3)
                            if len(rows) > 1 and pred.std() and real.std() else None),
            'mean_predicted_s': round(float(pred.mean()), 3),
            'mean_realised_s': round(float(real.mean()), 3),
            'rank_regret_proxy_s': round(float(np.abs(pred - real).max()), 3),
        }
    return out


def n7_offline():
    """VOID (kept for the record): the old fallback probe is invalid.

    It diffed the public ``fallback`` counter around ``action`` calls - the solver
    increments that counter *before* the first fallback action - and the Q4 hook was
    executed on Q3 arms, so it could never observe an event. Its earlier conclusion
    ("0 fallback states -> opportunity too small") is void; the corrected collector and
    measurement live in ``fallback_neighborhood.py`` (see ledger 8.2 / 8.5).
    """
    return {'void': True,
            'reason': 'action-time counter diff + Q4 hook on Q3 arms => events could never be observed',
            'replacement': 'fallback_neighborhood.py (directional_fallback entry capture)'}


def n8_accounting():
    """Absence-proof obligation accounting from a control run's public trace."""
    from audit import AuditPort
    from backend import LocalBackend
    from variants import VARIANTS
    cls, kwargs = VARIANTS[3]['skip12_probe60']
    out = []
    for seed in range(3497500, 3497508):
        backend = LocalBackend(seed, 3)
        port = AuditPort(backend)
        solver = cls(port, 3, **kwargs)

        class Probe(cls):
            def action(self, path, p, c):
                r = super().action(path, p, c)
                if path == '/measure':
                    self.ch_measures[c] = self.ch_measures.get(c, 0) + 1
                    self.positions.append(np.asarray(p, float).tolist())
                return r

        probe = Probe(port, 3, **kwargs)
        probe.ch_measures = {}
        probe.positions = []
        probe.run()
        found = set(probe.cleared)
        total = sum(probe.ch_measures.values())
        absent = sum(v for k, v in probe.ch_measures.items() if k not in found)
        station_positions = {tuple(np.round(s, 1)) for s in probe.stations}
        off_station = sum(1 for p in probe.positions
                          if tuple(np.round(np.asarray(p, float), 1)) not in station_positions)
        out.append({'seed': seed, 'targets': len(found), 'measures': total,
                    'absent_channel_measures': absent,
                    'absent_share': round(absent / max(1, total), 3),
                    'non_station_measures': off_station})
    return {'scenes': len(out),
            'mean_absent_measures': round(float(np.mean([o['absent_channel_measures'] for o in out])), 1),
            'mean_absent_share': round(float(np.mean([o['absent_share'] for o in out])), 3),
            'mean_non_station_measures': round(float(np.mean([o['non_station_measures'] for o in out])), 1),
            'per_scene': out}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {'grouping': group_report(), 'predictions': prediction_diagnostics()}
    try:
        payload['n7'] = n7_offline()
    except Exception as exc:                       # noqa: BLE001
        payload['n7'] = {'error': type(exc).__name__ + ': ' + str(exc)[:120]}
    try:
        payload['n8'] = n8_accounting()
    except Exception as exc:                       # noqa: BLE001
        payload['n8'] = {'error': type(exc).__name__ + ': ' + str(exc)[:120]}
    (OUT / 'reporting.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    for k in ('predictions', 'n7', 'n8'):
        v = payload[k]
        print(k, json.dumps({kk: vv for kk, vv in v.items() if kk != 'rows' and kk != 'per_scene'},
                            ensure_ascii=False)[:300])


if __name__ == '__main__':
    main()
