"""N4: clear-certificate decision regions and a conflict-reduction proxy.

Definitions
    K(F) = intersection over g in F of the 20 m clear disk around g   (a common safe
           clear point exists iff K(F) is non-empty)
    R_z  = {w : |g_w - z| <= 19.99}   for a candidate clear point z (finite worlds)

The proxy score of a measurement candidate q is the *conflict reduction* it causes:
execute the hypothetical measurement in every world, keep the worlds consistent with
the feedback (identical to the N1 world model), then count how many remaining world
pairs are still incompatible for a common clear point. A pair is incompatible when the
two positions are farther apart than 2 * 19.99 m - pairwise compatibility does NOT
imply a joint clear point (38 m equilateral triangle counterexample below).

This file is self-contained (no controller state): it takes a set of world positions
and returns region/conflict statistics, so the same-state experiment can compare this
ranking with the N1 time ranking on identical public states.
"""
import itertools
import math

import numpy as np

CLEAR_R = 19.99


def enclosing_radius(points):
    """Radius of the smallest enclosing circle (Welzl-free exact for <= 512 points)."""
    P = np.asarray(points, float)
    if len(P) == 0:
        return 0.
    if len(P) == 1:
        return 0.
    best = float('inf')
    n = len(P)
    for i, j in itertools.combinations(range(n), 2):
        for k in list(range(n)) + [None]:
            if k is None:
                c = (P[i] + P[j]) / 2.
            else:
                p, q, r = P[i], P[j], P[k]
                d = 2 * (p[0] * (q[1] - r[1]) + q[0] * (r[1] - p[1]) + r[0] * (p[1] - q[1]))
                if abs(d) < 1e-12:
                    continue
                ux = ((p @ p) * (q[1] - r[1]) + (q @ q) * (r[1] - p[1])
                      + (r @ r) * (p[1] - q[1])) / d
                uy = ((p @ p) * (r[0] - q[0]) + (q @ q) * (p[0] - r[0])
                      + (r @ r) * (q[0] - p[0])) / d
                c = np.array([ux, uy])
            rad = float(np.max(np.linalg.norm(P - c, axis=1)))
            if rad < best:
                best = rad
    return best if np.isfinite(best) else 0.


def common_clear_point_exists(points, tol=1e-9):
    """K(F) non-empty, i.e. a single 20 m disk covers every feasible position."""
    return enclosing_radius(points) <= CLEAR_R + tol


def conflict_pairs(points, tol=1e-9):
    """Number of world pairs that cannot share one clear point."""
    P = np.asarray(points, float)
    bad = 0
    for i, j in itertools.combinations(range(len(P)), 2):
        if float(np.linalg.norm(P[i] - P[j])) > 2 * CLEAR_R + tol:
            bad += 1
    return bad


def conflict_reduction(points, keep_mask, tol=1e-9):
    """How many pairwise conflicts a hypothetical observation removes."""
    P = np.asarray(points, float)
    keep_mask = np.asarray(keep_mask, bool)
    before = conflict_pairs(P, tol)
    after = conflict_pairs(P[keep_mask], tol) if keep_mask.any() else 0
    return before - after


def radius_reduction(points, keep_mask, tol=1e-9):
    """Continuous conflict proxy: how much the enclosing radius shrinks."""
    P = np.asarray(points, float)
    keep_mask = np.asarray(keep_mask, bool)
    before = enclosing_radius(P)
    after = enclosing_radius(P[keep_mask]) if keep_mask.any() else 0.
    return max(0., before - after)


def proxy_score_radius(world_positions, feedback_keep_masks):
    """Mean enclosing-radius reduction over the generated feedback outcomes."""
    P = np.asarray(world_positions, float)
    if not len(P):
        return 0.
    vals = [radius_reduction(P, np.asarray(m, bool)) for m in feedback_keep_masks]
    return float(np.mean(vals)) if vals else 0.


def proxy_score(world_positions, feedback_keep_masks):
    """Mean conflict reduction over the generated feedback outcomes (higher is better)."""
    P = np.asarray(world_positions, float)
    if not len(P):
        return 0.
    vals = [conflict_reduction(P, np.asarray(m, bool)) for m in feedback_keep_masks]
    return float(np.mean(vals)) if vals else 0.


def decision_region_containment(z, points, tol=1e-9):
    """Fraction of worlds a candidate clear point z can actually clear."""
    P = np.asarray(points, float)
    if not len(P):
        return 0.
    return float(np.mean(np.linalg.norm(P - np.asarray(z, float), axis=1) <= CLEAR_R + tol))
