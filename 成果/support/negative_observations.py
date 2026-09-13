"""Q3 received/not-received bisector half-plane (pure geometry only).

If one omnidirectional source is received at ``p`` and not received at ``q``,
then for its position ``g`` there is some reception radius ``R`` with

    ||g-p|| <= R < ||g-q||,

so ``||g-p|| < ||g-q||``, i.e. ``g`` lies in the closed half-plane closer to
``p`` than to ``q``:

    2 (q-p)^T g < ||q||^2 - ||p||^2.

This is a necessary condition derived from the reception model alone: no error
distribution, no prior, no knowledge of ``R`` and no access to simulator truth.
It therefore intersects safely with the existing convex feasible region.

Adapted from ``new_version/support/research/q3_model_v2/negative_observations.py``
(OptimizationA). Only the pure half-plane routine is reused here; the Q3
integration lives in ``OmniSearchSolver`` so it can share the joint scheduler.
"""
import numpy as np

from geometry import clip


def apply_negative_halfplanes(poly, positives, negatives):
    """Intersect ``poly`` with every received/not-received bisector half-plane.

    ``positives`` is the controller's ``self.obs[c]`` list of ``(position,
    bearing)`` tuples; only the positions matter here. ``negatives`` is a list
    of not-received measurement positions for the same channel. Returns
    ``(polygon, constraints_used)``; an empty polygon means the constraint set
    is numerically inconsistent and the caller must fall back to the outer bound.
    """
    result = np.asarray(poly).copy()
    used = 0
    for p, _angle in positives:
        for q in negatives:
            delta = q - p
            length = float(np.linalg.norm(delta))
            if not np.isfinite(length) or length <= 1e-7:
                # Contradictory/indistinguishable positions add no unsafe constraint.
                continue
            normal = delta / length
            # 1e-6 slack keeps the retained polygon an outer bound.
            bound = float(normal @ p + length / 2 + 1e-6)
            result = clip(result, normal, bound)
            used += 1
            if not len(result):
                return result, used
    return result, used
