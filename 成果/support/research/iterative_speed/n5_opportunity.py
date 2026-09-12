"""N5 opportunity scan: how often are two known-uncleared targets served together?

Public quantities only: at every routing decision of the strong Q3 control we read the
deferred (known, uncleared) target set, each target's certified feasible polygon, its
guaranteed-reception set  G_c = {q : max_{v in vertices(F_c)} |q - v| <= 1000}, and the
overlap of those sets for the two largest targets. We never look at the true sources.

Outputs a JSON statistic: per scene, the distribution of simultaneous known-uncleared
targets, the fraction of decisions with >= 2, how often the pairwise reception sets
overlap (a shared safe stop exists), and the single-target service transit cost.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from audit import AuditPort  # noqa: E402
from backend import LocalBackend  # noqa: E402
from variants import VARIANTS  # noqa: E402

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'results' / 'r90_n5_opportunity'
ARM = 'skip12_probe60'


def reception_set_vertices(self, c):
    poly = np.asarray(self.region(c)[0], float)
    return poly


def _overlap_point(pa, pb):
    """Approximate non-emptiness of {q: |q-a|<=1000 for all a in pa} ∩ (same for pb)."""
    cands = [pa.mean(axis=0), pb.mean(axis=0)]
    cands += [pa[i] for i in range(0, len(pa), 2)]
    cands += [pb[i] for i in range(0, len(pb), 2)]
    for pa_i in pa:
        for pb_j in pb:
            cands.append((pa_i + pb_j) / 2.)
    for q in cands:
        q = np.asarray(q, float)
        if float(np.max(np.linalg.norm(pa - q, axis=1))) <= 1000. + 1e-9 and \
           float(np.max(np.linalg.norm(pb - q, axis=1))) <= 1000. + 1e-9:
            return q
    return None


def main():
    seeds = [int(s) for s in sys.argv[1:]] or list(range(3497000, 3497012))
    cls, kwargs = VARIANTS[3][ARM]
    stats = []

    class Probe(cls):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.known_counts = []
            self.overlaps = 0
            self.pairs = 0
            self.service_transit = []

    for seed in seeds:
        backend = LocalBackend(seed, 3)
        port = AuditPort(backend)
        solver = Probe(port, 3, **kwargs)
        import omni_search as module
        original = module.search_route

        def patched(points, start):
            known = list(self_state.deferred)
            solver.known_counts.append(len(known))
            if len(known) >= 2:
                polys = [solver.region(k)[0] for k in known[:2]]
                solver.pairs += 1
                if _overlap_point(np.asarray(polys[0], float), np.asarray(polys[1], float)) is not None:
                    solver.overlaps += 1
                for p in points:
                    solver.service_transit.append(float(np.linalg.norm(np.asarray(p, float) - solver.pos)))
            return original(points, start)

        self_state = solver
        module.search_route = patched
        try:
            solver.run()
        finally:
            module.search_route = original
        stats.append({
            'seed': seed,
            'decisions': len(solver.known_counts),
            'mean_known': float(np.mean(solver.known_counts)) if solver.known_counts else 0.,
            'max_known': int(np.max(solver.known_counts)) if solver.known_counts else 0,
            'decisions_with_2plus': int(sum(1 for k in solver.known_counts if k >= 2)),
            'pairs_checked': solver.pairs,
            'pairs_with_shared_stop': solver.overlaps,
            'cleared': int(len(solver.cleared)),
        })
    total_pairs = sum(s['pairs_checked'] for s in stats)
    total_overlap = sum(s['pairs_with_shared_stop'] for s in stats)
    summary = {
        'arm': ARM, 'scenes': len(stats),
        'decisions_total': int(sum(s['decisions'] for s in stats)),
        'decisions_with_2plus': int(sum(s['decisions_with_2plus'] for s in stats)),
        'pairs_checked': total_pairs,
        'pairs_with_shared_stop': total_overlap,
        'shared_stop_rate': round(total_overlap / max(1, total_pairs), 3),
        'mean_known_targets': round(float(np.mean([s['mean_known'] for s in stats])), 2),
        'per_scene': stats,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'opportunity.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'per_scene'}, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
