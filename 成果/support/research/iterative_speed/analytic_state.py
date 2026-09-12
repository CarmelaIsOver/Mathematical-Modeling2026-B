"""N6: analytic elimination of the R grid for Q4, keeping continuous theta and R.

Fixed position g, public positive observations P+ and negatives P-:

    L(g) = max(1000, max_{p in P+} |p - g|)          # smallest receivable radius
    L(g) > 1500  ->  infeasible

Directional heading n(theta):
    * every positive p must satisfy  n . (p - g) >= 0        (closed half-circle)
    * every negative q with |q - g| <= L must satisfy n . (q - g) < 0
      (an out-of-range negative is explained by the radius instead)

Both constraints are half-circles in theta, so the feasible heading set is an exact
intersection of arcs, represented as a union of non-wrapping intervals on [0, 2pi) -
wrapping over +/-pi is handled explicitly and the strict (open) side of the negative
constraints is preserved by sampling strictly inside an interval.

Radius: never pinned to L. For a given theta the negatives that are front-facing must
be explained by distance, giving the strict bound R < |q - g|; the state therefore
exposes ``radius_interval(theta) -> (lo, hi)`` with lo = L and hi below the closest
front-facing negative. Omni sources have no heading; they are feasible iff every
negative is farther than L.

This only replaces the research *state construction*: candidates, scoring, the
certified region and every fallback are untouched.
"""
import math

import numpy as np

R_MAX = 1500.
R_MIN = 1000.
TWO_PI = 2 * math.pi
EPS = 1e-9


def _norm(a):
    a %= TWO_PI
    return a


def _arc_to_intervals(lo, hi):
    """Half-circle [lo, hi] (length pi, possibly wrapping) as intervals on [0, 2pi)."""
    lo, hi = _norm(lo), _norm(hi)
    if lo <= hi:
        return [(lo, hi)]
    return [(lo, TWO_PI), (0., hi)]


def _intersect_intervals(a, b):
    lo = max(a[0], b[0])
    hi = min(a[1], b[1])
    return None if hi < lo - EPS else (lo, hi)


def _merge(ivs):
    ivs = sorted(iv for iv in ivs if iv is not None and iv[1] - iv[0] > EPS)
    out = []
    for lo, hi in ivs:
        if out and lo <= out[-1][1] + EPS:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


class AnalyticState:
    """Feasible parameter set for one position g (continuous theta and R)."""

    __slots__ = ('g', 'L', 'feasible', 'kind', 'theta_intervals', 'negatives', 'positives')

    def __init__(self, g, L, feasible, kind, theta_intervals=None, negatives=(), positives=()):
        self.g = np.asarray(g, float)
        self.L = float(L)
        self.feasible = bool(feasible)
        self.kind = kind                          # 'directional' | 'omni' | None
        self.theta_intervals = list(theta_intervals or [])
        self.negatives = [np.asarray(q, float) for q in negatives]
        self.positives = [(np.asarray(p, float), float(a)) for p, a in positives]

    # -- radius set for a specific heading --------------------------------
    def radius_interval(self, theta):
        """(lo, hi, open_hi): R in [lo, hi) when open_hi, else [lo, hi]."""
        lo = self.L
        hi = R_MAX
        open_hi = False
        if self.kind == 'directional':
            n = np.array([math.cos(theta), math.sin(theta)])
            for q in self.negatives:
                d = q - self.g
                dist = float(np.linalg.norm(d))
                if dist <= lo:
                    continue
                if float(n @ d) >= -EPS:          # front-facing -> R must stay below dist
                    if dist < hi:
                        hi, open_hi = dist, True
        return lo, hi, open_hi

    def radius_ok(self, theta, R):
        lo, hi, open_hi = self.radius_interval(theta)
        if R < lo - EPS:
            return False
        return R < hi - EPS if open_hi else R <= hi + EPS

    def theta_representatives(self, k=3):
        reps = []
        for lo, hi in self.theta_intervals:
            if hi - lo <= 1e-9:
                reps.append(lo)
                continue
            for i in range(k):
                reps.append(lo + (hi - lo) * (i + 1) / (k + 1))
        return reps


def analyse_position(g, positives, negatives):
    """Exact existence test plus the continuous (theta, R) parameter set for g."""
    g = np.asarray(g, float)
    pos = [(np.asarray(p, float), float(a)) for p, a in positives]
    neg = [np.asarray(q, float) for q in negatives]
    L = R_MIN
    for p, _a in pos:
        L = max(L, float(np.linalg.norm(p - g)))
    if L > R_MAX:
        return AnalyticState(g, L, False, None, negatives=neg, positives=pos)

    omni_ok = all(float(np.linalg.norm(q - g)) > L for q in neg)
    ivs = None
    for p, _a in pos:
        d = p - g
        if float(np.linalg.norm(d)) < 1e-12:
            ivs = []
            break
        phi = math.atan2(d[1], d[0])
        h = _arc_to_intervals(phi - math.pi / 2, phi + math.pi / 2)   # closed
        ivs = h if ivs is None else _merge(
            [_intersect_intervals(a, b) for a in ivs for b in h])
        if not ivs:
            break
    if ivs is None:
        ivs = [(0., TWO_PI)]
    for q in neg:
        if not ivs:
            break
        d = q - g
        dist = float(np.linalg.norm(d))
        if dist <= L:
            if dist < 1e-12:
                ivs = []
                break
            phi = math.atan2(d[1], d[0])
            h = _arc_to_intervals(phi + math.pi / 2, phi + 3 * math.pi / 2)  # back-facing
            ivs = _merge([_intersect_intervals(a, b) for a in ivs for b in h])
    dir_ok = bool(ivs)
    if not dir_ok and not omni_ok:
        return AnalyticState(g, L, False, None, negatives=neg, positives=pos)
    kind = 'directional' if dir_ok else 'omni'
    return AnalyticState(g, L, True, kind, theta_intervals=ivs if dir_ok else [],
                         negatives=neg, positives=pos)


def is_directional(state):
    return state.feasible and state.kind == 'directional'
