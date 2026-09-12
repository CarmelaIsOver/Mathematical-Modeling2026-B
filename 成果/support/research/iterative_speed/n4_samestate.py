"""N4 same-state mechanism experiment.

At the SAME public decision states produced by the N1 arm, score every candidate two
ways and compare the rankings:

  * N1 time score      - full world rollout cost (mean + lambda tail)
  * N4 conflict score  - mean pairwise-conflict reduction of the hypothetical
                         observation (clear-certificate decision regions)

Reported per state: Spearman rank correlation, whether the top pick differs, and what
the N1 time model predicts for the N4 top pick versus the N1 top pick. Truth never
enters the controller; this is an offline diagnostic (development data).
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from audit import AuditPort  # noqa: E402
from backend import LocalBackend  # noqa: E402
from n4_regions import proxy_score, proxy_score_radius  # noqa: E402
from variants import VARIANTS  # noqa: E402
from world_rollout import WorldRolloutMixin  # noqa: E402

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'results' / 'r92_n4_samestate'


def spearman(a, b):
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    if len(a) < 2 or a.std() == 0 or b.std() == 0:
        return None
    ra = np.argsort(np.argsort(a))
    rb = np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


class N4Probe(WorldRolloutMixin):
    pass


def run_scene(seed, arm='n1_q3_m1'):
    cls, kwargs = VARIANTS[3][arm]

    class Probe(cls):
        def next_measure(self, c, poly, center, radius):
            base = self._base_pick(c, poly, center, radius)
            if radius > self.rollout_radius:
                return base
            worlds = self._world_set(c)
            if not worlds:
                return base
            cands = self._rollout_candidates(c, poly, center, radius) + ['optical']
            pos = [np.asarray(w[0], float) for w in worlds]
            rows = []
            for q in cands:
                if isinstance(q, str):
                    continue
                time_score = self._score_point(c, q, worlds)
                keep = []
                for w in worlds:
                    kind, _bearing = self._feedback(w, q, c)
                    keep.append(kind == 'direction')     # a bearing splits the world set
                n4 = proxy_score(pos, keep)
                n4r = proxy_score_radius(pos, keep)
                if time_score is not None:
                    rows.append({'q': [float(q[0]), float(q[1])], 'time': float(time_score),
                                 'n4': float(n4), 'n4_radius': float(n4r)})
            if len(rows) >= 2:
                ts = [r['time'] for r in rows]
                for tag, key in (('n4', 'n4'), ('n4_radius', 'n4_radius')):
                    ns = [r[key] for r in rows]
                    best_t = int(np.argmin(ts))
                    best_n = int(np.argmax(ns))
                    self.probe_rows.append({
                        'seed': seed, 'proxy': tag, 'n_candidates': len(rows),
                        'n4_std': float(np.std(ns)),
                        'spearman_time_vs_n4': spearman([-v for v in ts], ns),
                        'top_agrees': best_t == best_n,
                        'predicted_penalty_of_n4_top_s': rows[best_n]['time'] - rows[best_t]['time'],
                    })
            return super().next_measure(c, poly, center, radius)

    backend = LocalBackend(seed, 3)
    port = AuditPort(backend)
    solver = Probe(port, 3, **kwargs)
    solver.probe_rows = []
    solver.run()
    return solver.probe_rows


def main():
    seeds = [int(s) for s in sys.argv[1:]] or list(range(3497100, 3497106))
    rows = []
    for seed in seeds:
        try:
            rows.extend(run_scene(seed))
        except Exception as exc:                        # noqa: BLE001
            rows.append({'seed': seed, 'error': type(exc).__name__ + ': ' + str(exc)[:80]})
    ok = [r for r in rows if 'spearman_time_vs_n4' in r]
    defined = [r['spearman_time_vs_n4'] for r in ok if r['spearman_time_vs_n4'] is not None]
    by_proxy = {}
    for tag in ('n4', 'n4_radius'):
        sub = [r for r in ok if r.get('proxy') == tag]
        d = [r['spearman_time_vs_n4'] for r in sub if r['spearman_time_vs_n4'] is not None]
        by_proxy[tag] = {
            'states': len(sub),
            'states_with_defined_rank_correlation': len(d),
            'mean_n4_std': round(float(np.mean([r['n4_std'] for r in sub])), 4) if sub else None,
            'spearman_mean': round(float(np.mean(d)), 3) if d else None,
            'top_pick_agreement': round(float(np.mean([r['top_agrees'] for r in sub])), 3) if sub else None,
            'mean_predicted_penalty_s': round(float(np.mean([r['predicted_penalty_of_n4_top_s'] for r in sub])), 2) if sub else None,
        }
    summary = {
        'by_proxy': by_proxy,
        'states': len(ok), 'scenes': len({r['seed'] for r in ok}),
        'use': 'development_only_not_independent_acceptance',
        'states_with_defined_rank_correlation': len(defined),
        'states_with_degenerate_n4_ranking': len(ok) - len(defined),
        'rank_agreement_spearman_mean': round(float(np.mean(defined)), 3) if defined else None,
        'top_pick_agreement': round(float(np.mean([r['top_agrees'] for r in ok])), 3) if ok else None,
        'mean_predicted_penalty_of_n4_top_s': round(float(np.mean([r['predicted_penalty_of_n4_top_s'] for r in ok])), 2) if ok else None,
        'rows': rows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'n4_samestate.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'rows'}, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
