"""Minimal paired pilot: Q4 re-plan after a single localization measurement.

Baseline is the team's default ``JointSearchSolver``. The candidate resolves a
target one region-updating measurement at a time and returns to the joint route
after each step, then performs a blocking fallback once the per-channel
measurement budget is spent.

Arms
----
baseline : reschedule_after_step=False
step     : reschedule_after_step=True, target_measure_budget=8
stepskip : step plus ``step_skip_known=True`` (a station pass does not duplicate
           an open target's dedicated measurements)

For a given seed every arm sees the same ``LocalBackend``, so times are paired.
The two previously-known Q4 regressions are seeds 1900011 and 1900112.
"""
import argparse
import csv
import json
import statistics
import time
from pathlib import Path

from backend import LocalBackend
from audit import AuditPort
from joint_search import JointSearchSolver

ROOT = Path(__file__).resolve().parent
ARMS = ('baseline', 'step', 'stepskip')
BAD_CASES = (1900011, 1900112)


def make_solver(port, arm, problem=4, budget=8):
    if arm == 'baseline':
        return JointSearchSolver(port, problem)
    if arm in ('step', 'stepskip'):
        return JointSearchSolver(port, problem, reschedule_after_step=True,
                                 target_measure_budget=budget,
                                 step_skip_known=(arm == 'stepskip'))
    raise ValueError(f'Unknown arm {arm!r}')


def run_one(seed, arm, problem=4, budget=8):
    backend = LocalBackend(seed, problem)
    port = AuditPort(backend)
    started = time.perf_counter()
    result = make_solver(port, arm, problem, budget).run()
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


def summarize(rows, arms):
    by_arm = {arm: [r for r in rows if r['arm'] == arm] for arm in arms}
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
            'failed_clear': sum(r.get('failed_clear', 0) for r in rs),
            'measurements': sum(r.get('measure', 0) for r in rs),
            'small_region_probes': sum(r.get('small_region_probes', 0) for r in rs),
            'reschedule_steps': sum(r.get('reschedule_steps', 0) for r in rs),
            'reschedule_fallbacks': sum(r.get('reschedule_fallbacks', 0) for r in rs),
        }
    base = {r['seed']: r for r in by_arm.get('baseline', [])}
    for arm in arms:
        if arm == 'baseline':
            continue
        paired = [(r, r['mean_time_s'] / base[r['seed']]['mean_time_s'])
                  for r in by_arm.get(arm, []) if r['seed'] in base]
        if not paired:
            continue
        ratios = [ratio for _, ratio in paired]
        out[arm]['paired_mean_ratio'] = statistics.fmean(ratios)
        out[arm]['paired_median_ratio'] = statistics.median(ratios)
        out[arm]['paired_worst_ratio'] = max(ratios)
        out[arm]['paired_worst_seed'] = max(paired, key=lambda p: p[1])[0]['seed']
        out[arm]['paired_better'] = sum(1 for x in ratios if x < 1 - 1e-12)
        out[arm]['paired_equal'] = sum(1 for x in ratios if abs(x - 1) <= 1e-12)
        out[arm]['paired_worse'] = sum(1 for x in ratios if x > 1 + 1e-12)
        out[arm]['paired_worse_over_5pct'] = [
            {'seed': r['seed'], 'ratio': ratio} for r, ratio in paired if ratio > 1.05]
    return out


def main():
    ap = argparse.ArgumentParser(description='Q4 step-rescheduling paired pilot')
    ap.add_argument('--problem', type=int, default=4)
    ap.add_argument('--seeds', type=int, nargs='+', default=list(BAD_CASES))
    ap.add_argument('--arms', nargs='+', default=list(ARMS))
    ap.add_argument('--budget', type=int, default=8)
    ap.add_argument('--output', default=str(ROOT / 'results' / 'q4_reschedule'))
    a = ap.parse_args()

    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    rows, failures = [], []
    for seed in a.seeds:
        for arm in a.arms:
            try:
                r = run_one(seed, arm, a.problem, a.budget)
                rows.append(r)
                print(f'seed={seed} arm={arm:9s} cleared={r["cleared"]}/{r["paired_total_sources"]} '
                      f'mean={r["mean_time_s"]:.2f}s total={r["virtual_time_s"]:.1f}s '
                      f'fb={r.get("fallback", 0)} measures={r.get("measure", 0)} '
                      f'steps={r.get("reschedule_steps", 0)}', flush=True)
            except Exception as exc:  # keep going so one hard seed cannot hide the rest
                failures.append({'seed': seed, 'arm': arm,
                                 'error': type(exc).__name__ + ': ' + str(exc)})
                print(f'seed={seed} arm={arm:9s} FAILED {type(exc).__name__}: {exc}', flush=True)

    summary = {'problem': a.problem, 'seeds': list(a.seeds), 'arms': list(a.arms),
               'budget': a.budget, 'failures': failures,
               'aggregate': summarize(rows, a.arms)}
    (out / 'pilot_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    if rows:
        fields = sorted({k for r in rows for k in r})
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
