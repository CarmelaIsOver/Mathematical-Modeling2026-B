"""Prediction bookkeeping for research arms.

Unit rule
    Predictions produced inside the controller are *decision-level* costs in seconds
    accumulated over one scene. They are compared only with other decision-level
    numbers of the same kind; realised effects are reported separately from
    ``virtual_time_s`` (scene seconds). Nothing here sums decision-level remainders
    into a scene-level gain.

Buckets (kept separate on purpose)
    all      - mean predicted cost over the candidates considered at a decision
    adopted  - predicted saving of the action the policy actually took versus the
               baseline action at the same state
    rejected - best predicted saving among the alternatives it did not take
    Rejected proposals never explain execution results; they are reported for
    transparency only.

Credibility ("is the ranking trustworthy?") is judged from the counterfactual
artifact produced by ``counterfactual_lookahead.py``: one action deviation at the
same public-observation state, then the baseline policy again. Those decision states
are development data and must not be used for independent acceptance.
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent

BUCKETS = {
    'lookahead': {'adopted': 'lookahead_pred_adopted_s',
                  'rejected': 'lookahead_pred_rejected_max_s',
                  'all': 'lookahead_pred_all_sum_s',
                  'calls': 'lookahead_pred_calls',
                  'rejected_calls': 'lookahead_pred_rejected_calls'},
    'insertion': {'adopted': 'insertion_predicted_savings',
                  'rejected': None, 'all': None,
                  'calls': 'insertion_accepted', 'rejected_calls': None},
    'state_prediction': {'adopted': 'pred_predicted_gain_s',
                         'rejected': None, 'all': None,
                         'calls': 'pred_pred_calls', 'rejected_calls': None},
    'c2_options': {'adopted': 'pred_option_gain_s',
                   'rejected': None, 'all': None,
                   'calls': 'pred_option_calls', 'rejected_calls': None},
}


def compute(rows, control, arm, family, round_name='<synthetic>'):
    """Pure bookkeeping: units stay separated and nothing is summed into a gain."""
    keys = BUCKETS[family]
    ctl = {r['seed']: r for r in rows if r['variant'] == control}
    cand = [r for r in rows if r['variant'] == arm]
    pred_adopted = np.array([r.get(keys['adopted'], 0.) for r in cand], float)
    pred_rejected = (np.array([r.get(keys['rejected'], 0.) for r in cand], float)
                     if keys['rejected'] else np.zeros(len(cand)))
    pred_all = (np.array([r.get(keys['all'], 0.) for r in cand], float)
                if keys['all'] else np.zeros(len(cand)))
    realised = np.array([ctl[r['seed']]['virtual_time_s'] - r['virtual_time_s'] for r in cand], float)
    calls = np.array([r.get(keys['calls'], 0) for r in cand], float)
    out = {
        'round': round_name, 'control': control, 'arm': arm, 'family': family,
        'units': {'predicted': 's (decision-level accumulation over one scene)',
                  'realised': 's (scene total, virtual_time_s difference)'},
        'use': 'development_only_not_independent_acceptance',
        'n_scenes': len(cand),
        'decisions_with_prediction': int(calls.sum()),
        'buckets': {
            'all_candidates_mean_predicted_cost_s': round(
                float(np.sum([r.get('lookahead_pred_all_sum_s', 0.) for r in cand])
                      / max(1, int(np.sum([r.get('lookahead_pred_all_n', 0) for r in cand])))), 3),
            'adopted_predicted_saving_s': round(float(pred_adopted.mean()), 3),
            'rejected_best_predicted_saving_s': round(float(pred_rejected.mean()), 3),
        },
        'scene_realised_saving_s': round(float(realised.mean()), 3),
        'note': ('decision-level predictions are NOT summed into the scene saving; '
                 'rejected proposals are never used to explain realised results'),
    }
    return out, ctl, cand


def analyze(round_name, control, arm, family):
    folder = ROOT / 'results' / round_name
    rows = [json.loads(l) for l in (folder / 'metrics.jsonl').open(encoding='utf-8')]
    out, _ctl, _cand = compute(rows, control, arm, family, round_name)
    cf = folder / 'prediction_counterfactual.json'
    if cf.exists():
        cf_data = json.loads(cf.read_text(encoding='utf-8'))
        out['counterfactual'] = {
            'states': cf_data.get('states'),
            'sign_agreement': cf_data.get('sign_agreement'),
            'mean_absolute_error_s': cf_data.get('mean_absolute_error_s'),
            'mean_predicted_saving_s': cf_data.get('mean_predicted_saving_s'),
            'mean_realised_saving_s': cf_data.get('mean_realised_saving_s'),
        }
    (folder / 'prediction_analysis.json').write_text(json.dumps(out, indent=2, ensure_ascii=False),
                                                     encoding='utf-8')
    return out


def main():
    print(json.dumps(analyze(*sys.argv[1:5]), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
