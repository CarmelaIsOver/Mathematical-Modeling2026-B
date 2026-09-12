"""Direction C feasibility: can a small subset of the Q4 radial sites certify absence?

Absence certificate for one channel needs: every point of the 1800 m source disk is
within 1000 m (worst-case source receivable radius) of at least one scanned site.
This script answers, without touching any solver code:

  * exact cover radius of a given site subset (max over the disk of the distance to
    the nearest site), evaluated on Voronoi candidate points + a dense boundary ring;
  * whether ANY 7-subset of the 25 radial sites can cover the disk. The test uses a
    20 m grid as a *necessary* condition: an uncovered grid point is a genuine disk
    point, so a failing subset is provably infeasible (no tolerance argument needed);
  * a greedy/local-search minimum-cardinality cover and the true cover radius of the
    best subset found.

Nothing here is used by the solver; a failing verdict vetoes direction C outright.
"""
import itertools
import json
import math
from pathlib import Path

import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from geometry import search_stations  # noqa: E402

DISK_R = 1800.
RANGE = 1000.
OUT = Path(__file__).resolve().parent / 'results' / 'r30_q4_cert_geometry'


def candidate_points(S, boundary_step_deg=0.02):
    """Points where the max-min distance can attain its maximum.

    Interior maxima of min-distance sit on Voronoi vertices (circumcentres of site
    triples); boundary maxima are covered by a dense ring sample plus their local
    refinement. Candidates outside the disk are dropped.
    """
    pts = []
    n = len(S)
    for i, j, k in itertools.combinations(range(n), 3):
        a, b, c = S[i], S[j], S[k]
        d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
        if abs(d) < 1e-9:
            continue
        ux = ((a @ a) * (b[1] - c[1]) + (b @ b) * (c[1] - a[1]) + (c @ c) * (a[1] - b[1])) / d
        uy = ((a @ a) * (c[0] - b[0]) + (b @ b) * (a[0] - c[0]) + (c @ c) * (b[0] - a[0])) / d
        pts.append((ux, uy))
    th = np.radians(np.arange(0, 360, boundary_step_deg))
    pts.extend(zip(DISK_R * np.cos(th), DISK_R * np.sin(th)))
    P = np.asarray(pts, float)
    return P[np.linalg.norm(P, axis=1) <= DISK_R + 1e-9]


def cover_radius(S, extra=None, refine=True):
    """max over the disk of min-distance to S (m)."""
    S = np.asarray(S, float)
    P = candidate_points(S) if extra is None else np.vstack([candidate_points(S), extra])
    d = np.linalg.norm(P[:, None, :] - S[None, :, :], axis=2).min(axis=1)
    best = float(d.max())
    if refine:
        x = P[int(d.argmax())].copy()
        step = 4.0
        for _ in range(40):
            improved = False
            for ang in np.arange(0, 2 * math.pi, math.pi / 8):
                cand = x + step * np.array([math.cos(ang), math.sin(ang)])
                if np.linalg.norm(cand) > DISK_R:
                    continue
                val = float(np.linalg.norm(S - cand, axis=1).min())
                if val > best:
                    best, x, improved = val, cand, True
            if not improved:
                step *= 0.5
                if step < 1e-4:
                    break
    return best


def disk_grid(step):
    ax = np.arange(-DISK_R, DISK_R + step, step)
    X, Y = np.meshgrid(ax, ax)
    P = np.column_stack([X.ravel(), Y.ravel()])
    return P[np.linalg.norm(P, axis=1) <= DISK_R]


def grid_masks(S, grid):
    """Boolean matrix: grid point i covered by site j."""
    return np.linalg.norm(grid[:, None, :] - S[None, :, :], axis=2) <= RANGE


def any_7_subset_covers(S, grid, chunk=2000):
    """Necessary-condition sweep over all C(25,7) subsets using the 20 m grid."""
    n = len(S)
    cover = grid_masks(S, grid)
    combos = np.fromiter(itertools.chain.from_iterable(itertools.combinations(range(n), 7)),
                         dtype=np.int64)
    combos = combos.reshape(-1, 7)
    survivors = []
    for start in range(0, len(combos), chunk):
        block = combos[start:start + chunk]
        ok = np.zeros(len(block), bool)
        for slot in range(7):
            ok |= cover[:, block[:, slot]].all(axis=0)
        survivors.extend(np.where(ok)[0] + start)
    return combos, survivors


def greedy_min_cover(S, grid, size=None):
    cover = grid_masks(S, grid)
    remaining = np.ones(len(grid), bool)
    chosen = []
    limit = size or len(S)
    while remaining.any() and len(chosen) < limit:
        gain = cover[remaining].sum(axis=0)
        gain[chosen] = -1
        pick = int(gain.argmax())
        if gain[pick] <= 0:
            break
        chosen.append(pick)
        remaining &= ~cover[:, pick]
    return chosen, int((~remaining).sum())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    S = search_stations(4, 950., 'radial')
    r = np.linalg.norm(S, axis=1)
    ang = np.degrees(np.arctan2(S[:, 1], S[:, 0])) % 360
    inner = sorted([i for i in range(len(S)) if abs(r[i]) < 1e-6])
    ring1900 = sorted([i for i in range(len(S)) if abs(r[i] - 1900) < .5],
                      key=lambda i: ang[i])
    ring1645 = sorted([i for i in range(len(S)) if abs(r[i] - 1645.4) < .5],
                      key=lambda i: ang[i])
    ring950 = sorted([i for i in range(len(S)) if abs(r[i] - 950) < .5],
                     key=lambda i: ang[i])

    named = {
        'all25': list(range(len(S))),
        'center+6x1900(60deg)': inner + ring1900[::2],
        'center+6x1645': inner + ring1645,
        'center+6x950': inner + ring950,
        'center+12x1900': inner + ring1900,
        '6x1900(60deg)': ring1900[::2],
        '6x950': ring950,
    }
    res = {'parameters': {'disk_r': DISK_R, 'range': RANGE},
           'named': {}, 'search': {}}
    for name, idx in named.items():
        res['named'][name] = {
            'k': len(idx),
            'cover_radius_m': round(cover_radius(S[idx]), 2),
            'covers': bool(cover_radius(S[idx]) <= RANGE),
        }

    grid = disk_grid(20.)
    combos, survivors = any_7_subset_covers(S, grid)
    chosen, covered_pts = greedy_min_cover(S, grid)
    res['search'] = {
        'grid_points': int(len(grid)),
        'grid_step_m': 20.,
        'subsets_tested': int(len(combos)),
        'seven_subsets_passing_grid': int(len(survivors)),
        'greedy_k': len(chosen),
        'greedy_sites': [int(i) for i in chosen],
        'greedy_grid_points_covered': covered_pts,
        'greedy_cover_radius_m': round(cover_radius(S[chosen]), 2),
    }
    if survivors:
        best = None
        for s0 in survivors[:200]:
            rad = cover_radius(S[combos[s0]])
            if best is None or rad < best[0]:
                best = (rad, [int(i) for i in combos[s0]])
        res['search']['best_7_cover_radius_m'] = round(best[0], 2)
        res['search']['best_7_sites'] = best[1]
        res['search']['seven_subsets_exact_cover'] = int(best[0] <= RANGE)
    (OUT / 'summary.json').write_text(json.dumps(res, indent=2), encoding='utf-8')
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
