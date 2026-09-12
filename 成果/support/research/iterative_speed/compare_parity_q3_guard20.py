"""Production-entry vs research-arm parity check, Q3 ring guard, 20 seeds.

Compares run.py --q3-ring-guard {off,aggressive,conservative} (offline LocalBackend)
against research/iterative_speed/results/r25_q3_fixed200/metrics.jsonl on the SAME
seeds 3480000..3480019. Only per-seed verdicts are printed; the full metrics file is
never dumped to stdout.
"""
import csv, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROD = ROOT / 'results' / 'r26_q3_parity20_prod'
R25 = ROOT / 'results' / 'r25_q3_fixed200' / 'metrics.jsonl'
ARMS = [('off', 'baseline'), ('aggressive', 'guard1123_close_skip12'),
        ('conservative', 'guard1123_close_skip12_k6')]
SEEDS = list(range(3480000, 3480020))
FIELDS = [('mean_time_s', 'score_time_s'), ('measure', 'measure'), ('cleared', 'cleared'),
          ('virtual_time_s', 'virtual_time_s'), ('fallback', 'fallback'),
          ('failed_clear', 'failed_clear'),
          ('skipped_known_measurements', 'skipped_known_measurements'),
          ('stations_visited', 'stations_visited')]
# Counters that only exist in the production port (the research subclass never
# increments them), so r25 records a constant 0. Behaviour is unaffected; they
# are reported for transparency but excluded from the parity verdict.
PORT_ONLY = [('coverage_sites_cancelled', 'coverage_sites_cancelled')]


def load_r25():
    rows = {}
    with R25.open(encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            if r['seed'] in SEEDS:
                rows[(r['seed'], r['variant'])] = r
    return rows


def load_prod(arm):
    path = PROD / arm / 'local_q3.csv'
    with path.open(encoding='utf-8-sig', newline='') as f:
        return {int(r['seed']): r for r in csv.DictReader(f)}


def main():
    ref = load_r25()
    total = mismatch = 0
    for arm, variant in ARMS:
        prod = load_prod(arm)
        assert sorted(prod) == SEEDS, f'{arm}: seeds {sorted(prod)[:3]}...'
        bad = []
        port_only = []
        for seed in SEEDS:
            r = ref.get((seed, variant))
            if r is None:
                print(f'MISSING r25 row: {variant} seed={seed}')
                mismatch += 1
                continue
            p = prod[seed]
            for pkey, rkey in FIELDS:
                a, b = float(p[pkey]), float(r[rkey])
                total += 1
                if abs(a - b) > 1e-9:
                    bad.append((seed, pkey, a, b))
                    mismatch += 1
            for pkey, rkey in PORT_ONLY:
                if abs(float(p[pkey]) - float(r[rkey])) > 1e-9:
                    port_only.append((seed, pkey, float(p[pkey])))
        print(f'{arm:<13} vs {variant:<24} seeds=20/20  '
              f'{"IDENTICAL" if not bad else "MISMATCH"}'
              + (f'  (port-only counters differ on {len(port_only)} seeds)' if port_only else ''))
        for item in bad[:10]:
            print(f'   diff seed={item[0]} field={item[1]} prod={item[2]} r25={item[3]}')
        for seed, field, prod_v in port_only[:3]:
            print(f'   [port-only] seed={seed} {field} prod={prod_v} r25=0.0 (constant)')
    print(f'\ncompared fields: {total}, mismatches: {mismatch}')
    return 0 if mismatch == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
