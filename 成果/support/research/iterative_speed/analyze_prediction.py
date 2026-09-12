"""Prediction-error analysis: model-predicted saving vs realised paired saving.

Each direction records, per scene, the saving its cost model predicted for the actions
it chose (A: lookahead_pred_saving_s, B: insertion_predicted_savings, C:
pred_predicted_gain_s). This script compares those per-scene sums with the realised
paired saving (control_time - candidate_time) and writes ``prediction_analysis.json``.

Usage: python analyze_prediction.py <round> <control> <arm> <diagnostic-key>
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent


def analyze(round_name, control, arm, key):
    folder = ROOT / 'results' / round_name
    rows = [json.loads(l) for l in (folder / 'metrics.jsonl').open(encoding='utf-8')]
    ctl = {r['seed']: r for r in rows if r['variant'] == control}
    cand = [r for r in rows if r['variant'] == arm]
    pred = np.array([r.get(key, 0.) for r in cand], float)
    real = np.array([ctl[r['seed']]['score_time_s'] - r['score_time_s'] for r in cand], float)
    active = pred != 0.
    out = {
        'round': round_name, 'control': control, 'arm': arm, 'diagnostic_key': key, 'n': len(cand),
        'scenes_with_prediction': int(active.sum()),
        'mean_predicted_saving_s': round(float(pred.mean()), 2),
        'mean_realised_saving_s': round(float(real.mean()), 2),
        'sum_predicted_saving_s': round(float(pred.sum()), 1),
        'sum_realised_saving_s': round(float(real.sum()), 1),
        'mean_absolute_error_s': round(float(np.abs(pred - real).mean()), 2),
        'sign_agreement': (round(float((np.sign(pred) == np.sign(real)).mean()), 3) if len(cand) else None),
        'sign_agreement_when_predicted': (round(float((np.sign(pred[active]) == np.sign(real[active])).mean()), 3)
                                          if active.any() else None),
        'correlation': (round(float(np.corrcoef(pred, real)[0, 1]), 3)
                        if len(cand) > 1 and pred.std() > 0 and real.std() > 0 else None),
    }
    (folder / 'prediction_analysis.json').write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    return out


def main():
    print(json.dumps(analyze(*sys.argv[1:5]), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
