"""Batch seed evaluation of the current default policy.

Arms
----
Problem 3:
  default   OmniSearchSolver (team baseline, negative observations off)
  negative  default + negative_observations=True
Problem 4:
  default   JointSearchSolver (16-upper-bound discovery closure on)
  noclosure default + close_discovery_on_upper_bound=False   (A/B control)
  step      default + reschedule_after_step=True             (reference only)

Reports the full per-arm distribution (mean, sd, P50/P90/P95/P99, CVaR95 = mean
of the worst 5%, max) plus completion diagnostics and paired ratios against the
reference arm. Output CSV is append-only and resumable: already recorded
(seed, arm) pairs are skipped, so a long batch can be run in chunks.
"""
import argparse
import csv
import json
import math
import statistics
import time
from pathlib import Path

from backend import LocalBackend
from audit import AuditPort

ROOT = Path(__file__).resolve().parent
ARMS = {3: ('default', 'negative'), 4: ('default', 'noclosure', 'step')}
REFERENCE = {3: 'default', 4: 'default'}


def make_solver(port, problem, arm):
    if problem == 3:
        from omni_search import OmniSearchSolver
        if arm == 'default':
            return OmniSearchSolver(port, 3)
        if arm == 'negative':
            return OmniSearchSolver(port, 3, negative_observations=True)
    else:
        from joint_search import JointSearchSolver
        if arm == 'default':
            return JointSearchSolver(port, 4)
        if arm == 'noclosure':
            return JointSearchSolver(port, 4, close_discovery_on_upper_bound=False)
        if arm == 'step':
            return JointSearchSolver(port, 4, reschedule_after_step=True)
    raise ValueError(f'Unknown arm {arm!r} for problem {problem}')


def run_one(seed, problem, arm):
    backend = LocalBackend(seed, problem)
    port = AuditPort(backend)
    started = time.perf_counter()
    result = make_solver(port, problem, arm).run()
    result.update(seed=seed, problem=problem, arm=arm,
                  normal_exit=port.exited, sources=len(backend.sources),
                  wall_s=time.perf_counter() - started)
    if result['cleared'] != len(backend.sources) or not port.exited:
        raise RuntimeError(f'arm={arm} seed={seed}: incomplete run')
    return result


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(math.ceil(fraction * len(ordered))) - 1)]


def dist(values):
    if not values:
        return {}
    ordered = sorted(values)
    tail = ordered[max(0, len(ordered) - max(1, int(math.ceil(0.05 * len(ordered))))):]
    return {'n': len(values),
            'mean': statistics.fmean(values),
            'sd': statistics.stdev(values) if len(values) > 1 else 0.,
            'min': ordered[0], 'p50': percentile(values, .5), 'p90': percentile(values, .9),
            'p95': percentile(values, .95), 'p99': percentile(values, .99),
            'cvar95': statistics.fmean(tail), 'max': ordered[-1]}


def summarize(rows, problem):
    arms = ARMS[problem]
    by_arm = {arm: [r for r in rows if r['arm'] == arm] for arm in arms}
    out = {'problem': problem, 'reference': REFERENCE[problem], 'arms': {}}
    for arm, rs in by_arm.items():
        if not rs:
            continue
        means = [r['mean_time_s'] for r in rs]
        out['arms'][arm] = {
            'distribution_mean_time_s': dist(means),
            'mean_total_virtual_time_s': statistics.fmean([r['virtual_time_s'] for r in rs]),
            'sources_total': sum(r['sources'] for r in rs),
            'fallbacks': sum(r['fallback'] for r in rs),
            'failed_clear': sum(r['failed_clear'] for r in rs),
            'measurements': sum(r['measure'] for r in rs),
            'under_400_seeds': sum(1 for x in means if x <= 400),
        }
        if problem == 4:
            out['arms'][arm]['under_400_rate'] = (
                out['arms'][arm]['under_400_seeds'] / len(rs))
    ref = {r['seed']: r for r in by_arm.get(REFERENCE[problem], [])}
    for arm, rs in by_arm.items():
        if arm == REFERENCE[problem] or not ref:
            continue
        paired = [(r, r['mean_time_s'] / ref[r['seed']]['mean_time_s'])
                  for r in rs if r['seed'] in ref]
        if not paired:
            continue
        ratios = [ratio for _, ratio in paired]
        out['arms'][arm]['paired'] = {
            'mean_ratio': statistics.fmean(ratios),
            'median_ratio': statistics.median(ratios),
            'worst_ratio': max(ratios),
            'worst_seed': max(paired, key=lambda p: p[1])[0]['seed'],
            'better': sum(1 for x in ratios if x < 1 - 1e-12),
            'equal': sum(1 for x in ratios if abs(x - 1) <= 1e-12),
            'worse': sum(1 for x in ratios if x > 1 + 1e-12),
            'over_5pct': [{'seed': r['seed'], 'ratio': ratio}
                          for r, ratio in paired if ratio > 1.05],
        }
    return out


def main():
    ap = argparse.ArgumentParser(description='Batch seed evaluation')
    ap.add_argument('--problem', type=int, choices=[3, 4], required=True)
    ap.add_argument('--start', type=int, required=True)
    ap.add_argument('--count', type=int, default=40)
    ap.add_argument('--arms', nargs='+', default=None)
    ap.add_argument('--output', default=None)
    ap.add_argument('--summary-only', action='store_true')
    a = ap.parse_args()

    arms = a.arms or list(ARMS[a.problem])
    out = Path(a.output) if a.output else ROOT / 'results' / 'batch'
    out.mkdir(parents=True, exist_ok=True)
    metrics = out / f'q{a.problem}_metrics.csv'
    summary_path = out / f'q{a.problem}_summary.json'

    rows, done = [], set()
    if metrics.exists():
        with metrics.open(encoding='utf-8-sig') as f:
            rows = [dict(r) for r in csv.DictReader(f)]
        done = {(int(r['seed']), r['arm']) for r in rows}
        for r in rows:
            for key in ('seed', 'problem', 'sources'):
                r[key] = int(r[key])
            for key in r:
                if key not in ('seed', 'arm', 'problem', 'sources', 'normal_exit'):
                    try:
                        r[key] = float(r[key])
                    except ValueError:
                        pass

    if not a.summary_only:
        seeds = list(range(a.start, a.start + a.count))
        for seed in seeds:
            for arm in arms:
                if (seed, arm) in done:
                    continue
                result = run_one(seed, a.problem, arm)
                rows.append(result)
                print(f'q{a.problem} seed={seed} arm={arm:9s} sources={result["sources"]:2d} '
                      f'mean={result["mean_time_s"]:8.3f}s total={result["virtual_time_s"]:9.1f}s '
                      f'fb={result["fallback"]} failed={result["failed_clear"]} '
                      f'wall={result["wall_s"]:.1f}s', flush=True)
        fields = sorted({k for r in rows for k in r})
        with metrics.open('w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    summary = summarize([r for r in rows if r['arm'] in arms], a.problem)
    summary['seeds'] = sorted({r['seed'] for r in rows})
    summary_path.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
