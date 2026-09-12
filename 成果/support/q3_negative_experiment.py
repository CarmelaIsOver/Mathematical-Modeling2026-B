"""Minimal paired pilot: Q3 negative-observation half-planes on the joint scheduler.

Baseline is the team's default ``OmniSearchSolver`` (joint routing, no negative
constraints). The candidate reuses the received/not-received bisector half-plane
from ``new_version/support/research/q3_model_v2/negative_observations.py``.

Arms
----
baseline : use_negatives=False
tight    : use_negatives=True, certify_on_tight=True, negative_route=True
guard    : use_negatives=True, certify_on_tight=False, negative_route=True
measure  : use_negatives=True, certify_on_tight=False, negative_route=False

For a given seed every arm sees the same ``LocalBackend``, so times are paired.
``guard`` (renamed from ``safe``) is the only candidate for production: the
clearance certificate and the optical fallback always cover the
positive-reception outer bound. ``tight`` quantifies what the earlier ~3% figure
bought by letting negative constraints shrink the region used for the clearance
decision. ``measure`` keeps route centres and station-scan skips on the outer
bound, isolating the effect to the next-measurement choice.

The known degenerate scenario from the previous campaign is seed 990025.
"""
import argparse
import csv
import json
import statistics
import time
from pathlib import Path

from backend import LocalBackend
from audit import AuditPort
from omni_search import OmniSearchSolver

ROOT = Path(__file__).resolve().parent
ARMS = ('baseline', 'guard', 'tight', 'measure')
DEFAULT_SEEDS = (990025, 990000, 990001, 990002, 990003, 990004, 990005)


def make_solver(port, arm, problem=3):
    if arm == 'baseline':
        return OmniSearchSolver(port, problem)
    if arm == 'guard':
        return OmniSearchSolver(port, problem, negative_observations=True,
                                certify_on_tight=False, negative_route=True)
    if arm == 'tight':
        return OmniSearchSolver(port, problem, negative_observations=True,
                                certify_on_tight=True, negative_route=True)
    if arm == 'measure':
        return OmniSearchSolver(port, problem, negative_observations=True,
                                certify_on_tight=False, negative_route=False)
    raise ValueError(f'Unknown arm {arm!r}')


def run_one(seed, arm, problem=3):
    backend = LocalBackend(seed, problem)
    port = AuditPort(backend)
    started = time.perf_counter()
    result = make_solver(port, arm, problem).run()
    result.update(seed=seed, arm=arm, normal_exit=port.exited,
                  max_step_time_error_s=port.max_step_error_s,
                  paired_total_sources=len(backend.sources),
                  wall_s=time.perf_counter() - started)
    if result['cleared'] != len(backend.sources):
        raise RuntimeError(f'{arm} seed={seed}: cleared '
                           f'{result["cleared"]}/{len(backend.sources)}')
    if not port.exited:
        raise RuntimeError(f'{arm} seed={seed}: no normal exit')
    return result


def summarize(rows):
    by_arm = {arm: [r for r in rows if r['arm'] == arm] for arm in ARMS}
    out = {}
    for arm, rs in by_arm.items():
        if not rs:
            continue
        means = [r['mean_time_s'] for r in rs]
        out[arm] = {
            'n': len(rs),
            'mean_of_mean_time_s': statistics.fmean(means),
            'mean_total_time_s': statistics.fmean([r['virtual_time_s'] for r in rs]),
            'worst_mean_time_s': max(means),
            'fallbacks': sum(r.get('fallback', 0) for r in rs),
            'measurements': sum(r.get('measure', 0) for r in rs),
            'negative_observations': sum(r.get('negative_observations', 0) for r in rs),
            'negative_constraints': sum(r.get('negative_constraints', 0) for r in rs),
            'negative_region_fallbacks': sum(r.get('negative_region_fallbacks', 0) for r in rs),
        }
    base = {r['seed']: r for r in by_arm.get('baseline', [])}
    for arm in ('guard', 'tight', 'measure'):
        rs = by_arm.get(arm, [])
        if not rs or not base:
            continue
        # Only seeds with a successful baseline row can be paired.
        paired = [(r, r['mean_time_s'] / base[r['seed']]['mean_time_s'])
                  for r in rs if r['seed'] in base]
        if not paired:
            continue
        ratios = [ratio for _, ratio in paired]
        out[arm]['paired_mean_ratio'] = statistics.fmean(ratios)
        out[arm]['paired_worst_ratio'] = max(ratios)
        out[arm]['paired_worst_seed'] = max(paired, key=lambda pair: pair[1])[0]['seed']
        out[arm]['paired_worse_over_5pct'] = [
            {'seed': r['seed'], 'ratio': ratio}
            for r, ratio in paired if ratio > 1.05]
    return out


def main():
    ap = argparse.ArgumentParser(description='Q3 negative-observation paired pilot')
    ap.add_argument('--problem', type=int, default=3)
    ap.add_argument('--seeds', type=int, nargs='+', default=list(DEFAULT_SEEDS))
    ap.add_argument('--arms', nargs='+', default=list(ARMS))
    ap.add_argument('--output', default=str(ROOT / 'results' / 'q3_negative'))
    a = ap.parse_args()

    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    rows, failures = [], []
    for seed in a.seeds:
        for arm in a.arms:
            try:
                r = run_one(seed, arm, a.problem)
                rows.append(r)
                print(f'seed={seed} arm={arm:8s} cleared={r["cleared"]}/{r["paired_total_sources"]} '
                      f'mean={r["mean_time_s"]:.3f}s total={r["virtual_time_s"]:.3f}s '
                      f'fallbacks={r.get("fallback", 0)} neg={r.get("negative_observations", 0)}',
                      flush=True)
            except Exception as exc:  # keep going so one hard seed cannot hide the rest
                failures.append({'seed': seed, 'arm': arm,
                                 'error': type(exc).__name__ + ': ' + str(exc)})
                print(f'seed={seed} arm={arm:8s} FAILED {type(exc).__name__}: {exc}', flush=True)

    summary = {'problem': a.problem, 'seeds': list(a.seeds), 'arms': list(a.arms),
               'failures': failures, 'aggregate': summarize(rows)}
    (out / 'pilot_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    if rows:
        fields = sorted({k for r in rows for k in r if k != 'region_updates'})
        with (out / 'pilot_metrics.csv').open('w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k) for k in fields})
    print(json.dumps(summary['aggregate'], indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
