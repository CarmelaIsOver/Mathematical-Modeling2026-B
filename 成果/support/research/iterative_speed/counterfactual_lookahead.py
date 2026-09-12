"""Offline counterfactual for the short-lookahead ranking (development data).

For a small set of decision states of the *Q3 strong baseline* we ask the only
question that can validate a cost ranking: at the same public-observation state,
does taking the action the model preferred once, then returning to the baseline
policy, actually beat taking the baseline action there?

The evaluator replays the determinant simulator (LocalBackend) itself, which is
allowed because this file is evaluation-only: no truth, no seed information and no
backend state ever enters the controller or its predictor. The replay reaches the
decision state by re-executing the recorded action prefix, then forks:

  * control fork : baseline action at the decision, baseline policy afterwards
  * chosen fork  : the recorded model-preferred action, baseline policy afterwards

The realised saving is ``control_time - chosen_time`` (scene seconds). The predicted
saving comes from the lookahead's own decision log. These states are development
data and are excluded from independent acceptance.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from audit import AuditPort  # noqa: E402
from backend import LocalBackend  # noqa: E402
from study import run_one  # noqa: E402
from variants import VARIANTS  # noqa: E402

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'results' / 'r72_lookahead_counterfactual'
ARM = 'la_q3_service'
CONTROL = 'skip12_probe60'


class ForkPolicy:
    """Baseline policy with one deviation at the k-th active decision."""

    def __init__(self, base_cls, kwargs, k, action):
        self.base_cls = base_cls
        self.kwargs = kwargs
        self.k = k
        self.action = None if action is None else np.asarray(action, float)
        self.seen = 0

    def run(self, seed):
        base_cls, kwargs = self.base_cls, dict(self.kwargs)

        class _Forked(base_cls):
            def next_measure(_self, c, poly, center, radius):
                if radius <= kwargs.get('lookahead_radius', 400.):
                    idx = _self._fork_index = getattr(_self, '_fork_index', 0)
                    _self._fork_index = idx + 1
                    if idx == self.k:
                        return Self.action if self.action is not None else base_cls.next_measure(
                            _self, c, poly, center, radius)
                return base_cls.next_measure(_self, c, poly, center, radius)

        Self = self
        backend = LocalBackend(seed, 3)
        port = AuditPort(backend)
        solver = _Forked(port, 3, **kwargs)
        try:
            solver.run()
            return port.virtual_time, True
        except Exception:
            return port.virtual_time, False


def evaluate(seeds, states_per_scene=3):
    cls, kwargs = VARIANTS[3][CONTROL]
    control_kwargs = dict(kwargs)
    look_cls, look_kwargs = VARIANTS[3][ARM]
    rows = []
    for seed in seeds:
        solo = run_one((seed, 3, ARM, 'normal', None))
        picks = solo.get('lookahead_picks') or []
        pred_log = solo.get('lookahead_pred_log') or []
        if not picks:
            continue
        picks = [np.asarray(p, float) for p in picks]
        idx = np.linspace(0, len(picks) - 1, min(states_per_scene, len(picks)), dtype=int)
        for k in idx:
            chosen = ForkPolicy(cls, control_kwargs, int(k), picks[int(k)])
            control = ForkPolicy(cls, control_kwargs, int(k), None)
            t_chosen, ok1 = chosen.run(seed)
            t_control, ok2 = control.run(seed)
            predicted = float(pred_log[int(k)]['adopted_saving_s']) if int(k) < len(pred_log) else 0.
            rows.append({'seed': seed, 'decision': int(k),
                         'predicted_saving_s': round(predicted, 3),
                         'realised_saving_s': round(t_control - t_chosen, 3),
                         'complete': bool(ok1 and ok2)})
    if not rows:
        summary = {'states': 0}
    else:
        pred = np.array([r['predicted_saving_s'] for r in rows], float)
        real = np.array([r['realised_saving_s'] for r in rows], float)
        summary = {
            'states': len(rows),
            'seeds': sorted({r['seed'] for r in rows}),
            'mean_predicted_saving_s': round(float(pred.mean()), 3),
            'mean_realised_saving_s': round(float(real.mean()), 3),
            'mean_absolute_error_s': round(float(np.abs(pred - real).mean()), 3),
            'sign_agreement': round(float((np.sign(pred) == np.sign(real)).mean()), 3),
            'correlation': (round(float(np.corrcoef(pred, real)[0, 1]), 3)
                            if len(rows) > 1 and pred.std() > 0 and real.std() > 0 else None),
        }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'prediction_counterfactual.json').write_text(
        json.dumps({'use': 'development_only_not_independent_acceptance',
                    'arm': ARM, 'control': CONTROL, 'rows': rows, **summary},
                   indent=2, ensure_ascii=False), encoding='utf-8')
    return {'summary': summary, 'rows': rows}


def main():
    seeds = [int(s) for s in sys.argv[1:]] or [3493000, 3493001, 3493002, 3493003, 3493004]
    out = evaluate(seeds)
    print(json.dumps(out['summary'], indent=2, ensure_ascii=False))
    for r in out['rows']:
        print(f"  seed={r['seed']} k={r['decision']} predicted={r['predicted_saving_s']:+8.2f}s "
              f"realised={r['realised_saving_s']:+8.2f}s")


if __name__ == '__main__':
    main()
