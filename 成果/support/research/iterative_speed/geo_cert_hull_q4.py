"""Direction C feasibility, correct Q4 criterion (directional sources).

Q4 sources are directional (`backend.py`: visible only when (p - source)·dir >= 0),
so a channel is absent only if, for EVERY point q of the 1800 m disk, the scanned
sites within 1000 m of q are NOT contained in one open half-plane through q. That is
equivalent to: q lies in the interior of the convex hull of its eligible sites,
equivalently the largest angular gap between eligible sites seen from q is < 180 deg.

This script evaluates, on a fine disk grid, the uncovered area for
  * the full 25-site radial layout (sanity: must be 0),
  * each single-station removal (reproduces R23's indispensability claim),
  * candidate 7-site certificate sets (including the best pure disc-cover 7-set).

Pure geometry: no solver code is imported or modified.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from geometry import search_stations  # noqa: E402

OUT = Path(__file__).resolve().parent / 'results' / 'r30_q4_cert_geometry'
DISK_R, RANGE, STEP = 1800., 1000., 10.


def disk_grid(step):
    ax = np.arange(-DISK_R, DISK_R + step, step)
    X, Y = np.meshgrid(ax, ax)
    P = np.column_stack([X.ravel(), Y.ravel()])
    return P[np.linalg.norm(P, axis=1) <= DISK_R]


def uncovered(grid, dist, theta, subset, margin_deg=0.0):
    """Grid points not strictly inside the hull of eligible sites (count + fraction)."""
    elig = dist[:, subset] <= RANGE
    k = elig.sum(axis=1)
    A = np.where(elig, theta[:, subset], np.inf)
    A = np.sort(A, axis=1)
    n = A.shape[1]
    idx = np.arange(n)[None, :]
    nxt = np.where(idx + 1 < k[:, None],
                   np.take_along_axis(A, np.minimum(idx + 1, n - 1), axis=1),
                   A[:, :1] + 2 * np.pi)
    with np.errstate(invalid='ignore'):
        gaps = nxt - A
        gaps[~np.isfinite(gaps)] = np.nan
        max_gap = np.nanmax(gaps, axis=1)
    covered = (k >= 3) & (max_gap < np.pi - np.radians(margin_deg))
    return int((~covered).sum()), int(len(grid))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    S = search_stations(4, 950., 'radial')
    r = np.linalg.norm(S, axis=1)
    ang = np.degrees(np.arctan2(S[:, 1], S[:, 0])) % 360
    inner = [i for i in range(len(S)) if r[i] < 1e-6]
    R1900 = sorted([i for i in range(len(S)) if abs(r[i] - 1900) < .5], key=lambda i: ang[i])
    R1645 = sorted([i for i in range(len(S)) if abs(r[i] - 1645.4) < .5], key=lambda i: ang[i])
    R950 = sorted([i for i in range(len(S)) if abs(r[i] - 950) < .5], key=lambda i: ang[i])

    grid = disk_grid(STEP)
    diff = S[None, :, :] - grid[:, None, :]
    dist = np.linalg.norm(diff, axis=2)
    theta = np.arctan2(diff[:, :, 1], diff[:, :, 0])

    res = {'grid_step_m': STEP, 'grid_points': int(len(grid)),
           'criterion': 'largest angular gap of eligible (<=1000m) sites < 180deg',
           'named': {}, 'single_removal_uncovered': {}}

    named = {
        'all25': list(range(25)),
        'center+6x1645 (best disc-cover 7-set)': inner + R1645,
        'center+6x1900(60deg)': inner + R1900[::2],
        'center+6x950': inner + R950,
        'center+6x1900+6x950 (13)': inner + R1900[::2] + R950,
        'center+12x1900 (13)': inner + R1900,
    }
    for name, idx in named.items():
        bad, tot = uncovered(grid, dist, theta, idx)
        res['named'][name] = {'k': len(idx), 'uncovered_points': bad,
                              'uncovered_area_m2': round(bad * STEP * STEP, 1),
                              'covers': bad == 0}
    for i in range(25):
        bad, _ = uncovered(grid, dist, theta, [j for j in range(25) if j != i])
        res['single_removal_uncovered'][str(i)] = bad
    res['single_removal_zero_count'] = int(sum(v == 0 for v in res['single_removal_uncovered'].values()))
    (OUT / 'hull_summary.json').write_text(json.dumps(res, indent=2), encoding='utf-8')
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
