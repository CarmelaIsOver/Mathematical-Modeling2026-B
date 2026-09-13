"""Q3 research mixin: teammate negative-observation outer relaxation.

Difference from the local opt-in option (`--negative-observations`, ledger A4):
  * A4 keeps a *bisector half-plane* from a received/not-received pair (needs a prior
    positive reception of the same channel) and uses it for planning only; the
    certificate stays on the positive outer bound.
  * Here the teammate's *range* exclusion is used: a Q3 no_signal from an uncleared
    source implies distance > 1000 m (the smallest receivable radius), so the truth is
    in poly minus a 999.999 m disk. A convex outer relaxation of that remainder is built
    from surviving polygon vertices plus polygon-edge/circle intersections, and the
    region becomes poly intersected with those half-planes (+1e-5 m slack), applied
    sequentially over all recorded negatives.

Inclusion argument (no feasible point is lost):
  1. radius >= 1000 m, so no_signal implies dist > 1000 > 999.999; excluding the
     999.999 m disk keeps every feasible point.
  2. the remainder's extreme points are polygon vertices outside the disk or
     edge/circle intersections - both collected - so hull(collected) contains the
     remainder.
  3. poly intersected with half-planes of a superset stays a superset of the truth, so
     certificates built on this region remain sound.
  4. sequential application only enlarges the hull at each step, hence conservative.

Contradictory public observations (region would become empty) keep the last valid region
and increment ``neg_hull_contradictions`` instead of failing.
"""
import numpy as np

from geometry import enclosing_circle
from localization_service import outside_disk_hull


class NegativeHullMixin:
    def _setup_neg_hull(self, negative_hull=True):
        self.neg_hull_enabled = bool(negative_hull)
        self.neg_hull_negatives = {c: [] for c in range(1, 21)}
        self.neg_hull_cache = {}
        self.diagnostics.update(neg_hull_negatives=0, neg_hull_contradictions=0,
                                neg_hull_region_updates=0, neg_hull_cache_hits=0)

    def _record_negative(self, path, p, c, response):
        if path == '/measure' and response.get('measure_result') == 'no_signal' \
                and c not in self.cleared:
            self.neg_hull_negatives[c].append(np.asarray(p, float))
            self.diagnostics['neg_hull_negatives'] += 1

    def region(self, c):
        poly, center, radius = super().region(c)
        if not self.neg_hull_enabled:
            return poly, center, radius
        negs = self.neg_hull_negatives.get(c) or []
        if not negs:
            return poly, center, radius
        key = (len(self.obs[c]), len(negs))
        cached = self.neg_hull_cache.get(c)
        if cached is not None and cached[0] == key:
            self.diagnostics['neg_hull_cache_hits'] += 1
            return cached[1], cached[2], cached[3]
        cur = np.asarray(poly, float)
        for q in negs:
            try:
                nxt = outside_disk_hull(cur, q)
            except RuntimeError:
                self.diagnostics['neg_hull_contradictions'] += 1
                break
            if nxt is None or not len(nxt):
                self.diagnostics['neg_hull_contradictions'] += 1
                break
            cur = np.asarray(nxt, float)
        center2, radius2 = enclosing_circle(cur)
        self.diagnostics['neg_hull_region_updates'] += 1
        self.neg_hull_cache[c] = (key, cur, center2, radius2)
        return cur, center2, radius2
