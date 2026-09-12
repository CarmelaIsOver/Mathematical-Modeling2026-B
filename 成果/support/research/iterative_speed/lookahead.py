"""Direction A: complete-service-cost short lookahead for localization picks.

J(a) = charged action cost of a
     + E_branch[ clear leg from a + exit leg to the next retained task ]
     + lam * ( worst-branch cost - mean-branch cost )

Design rules (round 5 revision)
  * Branch set: bearing bins from ``outcomes`` plus the ``no_signal`` and ``near``
    outcomes. Compression never drops ``no_signal``/``near``; only the bearing bins
    are subsampled. A branch is created only when it is geometrically feasible
    (``near`` requires q to be inside the posterior or within the 5 m clear radius).
  * Cost model: 1 s per 5 m, 5 s per measure, 1 s per channel switch, 3 s optical
    + 2 s laser per successful clear, charged exactly as the backend does.
  * Hypothesised continuation: a lightweight assumed state (no backend, no mutation
    of the real controller) advances position, channel, observations and measured
    points, then the *baseline* policy continues for a bounded number of steps.
    Truncated branches are reported as such; they never masquerade as a finished
    clear.
  * Ranking: coarse scores only shortlist candidates; the winner is chosen among
    fine scores of the same scale, and the strong-baseline action is always in the
    final comparison.
  * Prediction bookkeeping keeps three buckets per decision: all candidates, the
    adopted action, the best rejected action. They are diagnostics only - they are
    never summed into a scene-level gain.
"""
import math

import numpy as np

from active_localization import ActiveLocalizationSolver, outcomes, radius_bound
from geometry import bearing_clip
from joint_search import JointSearchSolver
from omni_search import OmniSearchSolver
from solver import Solver, safe_clear_point


def _outcomes_with_angles(poly, q, bins=12):
    """Bearing bins with their raw representative angle (mirror of outcomes()).

    The representative angle is the centre of the bin's wedge, i.e. the actual
    feedback the branch stands for; it is stored in the assumed history instead of
    an angle re-derived from the posterior centroid.
    """
    poly = np.asarray(poly, float)
    q = np.asarray(q, float)
    delta = poly - q
    edges = np.roll(poly, -1, axis=0) - poly
    rel = q - poly
    crosses = edges[:, 0] * rel[:, 1] - edges[:, 1] * rel[:, 0]
    if np.all(crosses >= -1e-8) or np.all(crosses <= 1e-8):
        return []
    middle = math.atan2(*(poly.mean(axis=0) - q)[::-1])
    angles = np.angle(np.exp(1j * (np.arctan2(delta[:, 1], delta[:, 0]) - middle)))
    lo = float(angles.min()) - math.radians(0.05)
    hi = float(angles.max()) + math.radians(0.05)
    step = (hi - lo) / bins
    out = []
    for i in range(bins):
        rel_angle = lo + (i + .5) * step
        post = bearing_clip(poly, q, math.degrees(middle + rel_angle), 0.05 + math.degrees(step) / 2)
        if len(post):
            out.append((post, step, (math.degrees(middle + rel_angle)) % 360.))
    return out


def _point_poly_distance(poly, q):
    """Distance from q to the closed feasible set (0 inside, else nearest edge)."""
    poly = np.asarray(poly, float)
    q = np.asarray(q, float)
    if _inside_convex(poly, q):
        return 0.
    best = float('inf')
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ab = b - a
        denom = float(ab @ ab)
        t = 0. if denom <= 1e-12 else float(np.clip(((q - a) @ ab) / denom, 0., 1.))
        best = min(best, float(np.linalg.norm(q - (a + t * ab))))
    return best


class _HypState:
    """Assumed observation state for continuation; never touches the real solver."""

    __slots__ = ('pos', 'channel', 'problem', 'key', 'obs', 'measured', 'diagnostics')

    def __init__(self, key, pos, channel, problem, obs_c, measured_c, diagnostics):
        self.key = int(key)
        self.pos = np.asarray(pos, float)
        self.channel = int(channel)
        self.problem = problem
        self.obs = {self.key: list(obs_c)}
        self.measured = {self.key: [np.asarray(p, float) for p in measured_c]}
        self.diagnostics = diagnostics

    def copy(self):
        return _HypState(self.key, self.pos, self.channel, self.problem, self.obs[self.key],
                         self.measured[self.key], self.diagnostics)

    def advance(self, c, q, ang=None):
        q = np.asarray(q, float)
        self.pos = q
        self.measured[self.key].append(q)
        if ang is not None:
            self.obs[self.key].append((q, float(ang)))
        self.channel = int(c)


def _inside_convex(poly, q, eps=1e-9):
    n = len(poly)
    if n < 3:
        return True
    pos = neg = False
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        cross = (b[0] - a[0]) * (q[1] - a[1]) - (b[1] - a[1]) * (q[0] - a[0])
        if cross > eps:
            pos = True
        elif cross < -eps:
            neg = True
        if pos and neg:
            return False
    return True


class LookaheadMixin:
    def _setup_lookahead(self, lookahead_radius=400., lam=.5, max_candidates=12,
                         max_branches=8, mode='service', continue_depth=2):
        self.lookahead_radius = float(lookahead_radius)
        self.lookahead_lam = float(lam)
        self.lookahead_max_candidates = int(max_candidates)
        self.lookahead_max_branches = int(max_branches)
        self.lookahead_mode = mode
        self.lookahead_depth = int(continue_depth)
        self.diagnostics.update(
            lookahead_calls=0, lookahead_active=0, lookahead_changed=0,
            lookahead_branches=0, lookahead_budget_aborts=0, lookahead_numeric_aborts=0,
            lookahead_truncated=0,
            lookahead_pred_all_sum_s=0., lookahead_pred_all_n=0,
            lookahead_pred_adopted_s=0., lookahead_pred_rejected_max_s=0.,
            lookahead_pred_calls=0, lookahead_pred_rejected_calls=0)
        self.lookahead_budget = int(max(1, self.lookahead_max_candidates * self.lookahead_max_branches * 2))
        # Development / counterfactual support: the offline evaluator reads the
        # per-decision picks to fork a single deviation and restore the baseline.
        # They live in diagnostics so they are saved with the run metrics.
        self.diagnostics['lookahead_picks'] = []
        self.diagnostics['lookahead_pred_log'] = []

    # ---- helpers -------------------------------------------------------
    def _next_task_point(self, c):
        pts = [self.stations[i] for i in self.pending_stations]
        for k in self.deferred:
            if k == c:
                continue
            try:
                pts.append(self.region(k)[1])
            except Exception:
                pass
        if not pts:
            return None
        arr = np.asarray(pts, float)
        return arr[int(np.argmin(np.linalg.norm(arr - self.pos, axis=1)))]

    def _base_pick(self, c, poly, center, radius):
        """Strong-baseline measurement choice (overridden per problem)."""
        return Solver.next_measure(self, c, poly, center, radius)

    def _branches(self, c, q, poly, bins=12):
        """Feasible observation branches with their raw feedback representative.

        Physics constraints (P0):
          * no_signal needs a feasible position farther than 1000 m from q; for a
            convex posterior the maximum distance is attained at a vertex, so
            ``max_vertex_distance <= 1000`` makes no_signal impossible (the smallest
            possible receivable radius is 1000 m and no orientation can hide it).
          * near needs the source within the 5 m clear radius of q, measured to the
            whole feasible set (point-to-edge included), not only to its vertices.
        """
        q = np.asarray(q, float)
        out = [(post, 1., 'direction', ang) for post, _w, ang in _outcomes_with_angles(poly, q, bins)]
        verts = np.asarray(poly, float)
        if len(verts):
            far = float(np.max(np.linalg.norm(verts - q, axis=1)))
            if far > 1000. + 1e-9:
                out.append((verts, 1., 'no_signal', None))
        near_ok = len(verts) >= 3 and _point_poly_distance(verts, q) <= 5. + 1e-9
        if near_ok:
            out.append((np.asarray([q], float), 1., 'near', None))
        return out

    def _compress(self, branches):
        """Subsample bearing bins only; never drop no_signal/near."""
        near = [b for b in branches if b[2] == 'near']
        nosig = [b for b in branches if b[2] == 'no_signal']
        direc = [b for b in branches if b[2] == 'direction']
        room = max(1, self.lookahead_max_branches - len(near) - len(nosig))
        if len(direc) > room:
            idx = np.linspace(0, len(direc) - 1, room, dtype=int)
            direc = [direc[i] for i in idx]
        return direc + nosig + near

    def _assumed_state(self, c, q):
        return _HypState(c, q, c, self.problem, self.obs[c], self.measured[c], self.diagnostics)

    def _advance(self, state, c, q, post, kind, angle=None):
        """Advance a copy of the assumed state for one branch outcome.

        The raw feedback representative stored by ``_branches`` is reused, so the
        assumed history keeps the feedback the branch actually stands for and the
        same world/position/channel always yields the same reading.
        """
        if kind == 'near':
            return None, None
        nxt = state.copy()
        if kind == 'no_signal':
            nxt.advance(c, q, None)
            return nxt, post
        if angle is None:
            centroid = np.asarray(post, float).mean(axis=0)
            angle = math.degrees(math.atan2(centroid[1] - q[1], centroid[0] - q[0])) % 360.
        nxt.advance(c, q, float(angle))
        return nxt, post

    def _exit_cost(self, end, next_task):
        if next_task is None:
            return 0.
        return float(np.linalg.norm(np.asarray(end, float) - np.asarray(next_task, float))) / 5

    def _continue_cost(self, state, c, poly, center, radius, next_task, depth):
        """Remaining charged cost from an assumed state until clear plus exit.

        Uses the baseline policy for a bounded number of steps. When the bound is
        reached without a certificate the shortcut is reported (``lookahead_truncated``)
        and priced by a documented lower-bound-style estimate, never as a finished
        clear.
        """
        rb, mb = radius_bound(poly)
        if rb <= 19.99:
            cp = np.asarray(safe_clear_point(state.pos, mb, rb), float)
            return float(np.linalg.norm(state.pos - cp)) / 5 + 5. + self._exit_cost(cp, next_task)
        if depth <= 0:
            self.diagnostics['lookahead_truncated'] += 1
            # Truncation estimate: one more measure at the posterior centre plus a
            # residual half-radius walk. Explicitly a heuristic, not a certificate.
            return (float(np.linalg.norm(state.pos - mb)) / 5 + 5. + 0.5 * float(rb) / 5
                    + self._exit_cost(mb, next_task))
        q2 = Solver.next_measure(state, c, poly, mb, rb)
        if q2 is None:
            self.diagnostics['lookahead_truncated'] += 1
            return (float(np.linalg.norm(state.pos - mb)) / 5 + 5. + 0.5 * float(rb) / 5
                    + self._exit_cost(mb, next_task))
        q2 = np.asarray(q2, float)
        action = float(np.linalg.norm(state.pos - q2)) / 5 + 5. + int(c != state.channel)
        branches = self._compress(self._branches(c, q2, poly))
        costs = []
        for post, _w, kind, ang in branches:
            if kind == 'near':
                costs.append(5. + self._exit_cost(q2, next_task))
                continue
            nxt, npoly = self._advance(state, c, q2, post, kind, ang)
            nrb, nmb = radius_bound(npoly)
            costs.append(self._continue_cost(nxt, c, npoly, nmb, nrb, next_task, depth - 1))
        costs = np.asarray(costs, float)
        return action + float(costs.mean()) + self.lookahead_lam * float(costs.max() - costs.mean())

    # ---- scoring -------------------------------------------------------
    def _coarse_score(self, c, q, poly, next_task):
        """Cheap screening score; never used for the final ranking."""
        branches = self._compress(self._branches(c, q, poly))
        if not branches:
            return None
        self.diagnostics['lookahead_branches'] += len(branches)
        action = float(np.linalg.norm(np.asarray(q, float) - self.pos)) / 5 + 5. + int(c != self.channel)
        costs = []
        for post, _w, kind, ang in branches:
            if kind == 'near':
                costs.append(5. + self._exit_cost(q, next_task))
                continue
            rb, mb = radius_bound(post)
            if kind == 'no_signal':
                costs.append(float(np.linalg.norm(np.asarray(q, float) - mb)) / 5 + 5. + 0.5 * float(rb) / 5
                             + self._exit_cost(mb, next_task))
                continue
            if rb <= 19.99:
                cp = np.asarray(safe_clear_point(q, mb, rb), float)
                costs.append(float(np.linalg.norm(np.asarray(q, float) - cp)) / 5 + 5.
                             + self._exit_cost(cp, next_task))
            else:
                costs.append(float(np.linalg.norm(np.asarray(q, float) - mb)) / 5 + 5. + 0.5 * float(rb) / 5
                             + self._exit_cost(mb, next_task))
        costs = np.asarray(costs, float)
        if self.lookahead_mode == 'cand_paper':
            return action + float(costs.max())
        return action + float(costs.mean()) + self.lookahead_lam * float(costs.max() - costs.mean())

    def _fine_score(self, c, q, poly, next_task):
        """Same-scale score used for the final ranking."""
        state = self._assumed_state(c, q)
        branches = self._compress(self._branches(c, q, poly))
        if not branches:
            return None
        action = float(np.linalg.norm(np.asarray(q, float) - self.pos)) / 5 + 5. + int(c != self.channel)
        costs = []
        for post, _w, kind, ang in branches:
            if kind == 'near':
                costs.append(5. + self._exit_cost(q, next_task))
                continue
            nxt, npoly = self._advance(state, c, q, post, kind)
            nrb, nmb = radius_bound(npoly)
            costs.append(self._continue_cost(nxt, c, npoly, nmb, nrb, next_task, self.lookahead_depth - 1))
        costs = np.asarray(costs, float)
        if not np.all(np.isfinite(costs)):
            return None
        if self.lookahead_mode == 'cand_paper':
            return action + float(costs.max())
        return action + float(costs.mean()) + self.lookahead_lam * float(costs.max() - costs.mean())

    def _score_candidates(self, c, poly, center, radius, cands, fine_top=3):
        """Coarse shortlist, then a final ranking on one common (fine) scale."""
        next_task = self._next_task_point(c)
        base = self._base_pick(c, poly, center, radius)
        coarse = []
        spent = 0
        for q in cands:
            if spent >= self.lookahead_budget:
                self.diagnostics['lookahead_budget_aborts'] += 1
                break
            sc = self._coarse_score(c, q, poly, next_task)
            spent += self.lookahead_max_branches
            if sc is not None and np.isfinite(sc):
                coarse.append((sc, np.asarray(q, float)))
        if not coarse:
            return None, None, None
        coarse.sort(key=lambda t: t[0])
        shortlist = [q for _, q in coarse[:fine_top]]
        if base is not None and not any(float(np.linalg.norm(b - np.asarray(base, float))) < .1 for b in shortlist):
            shortlist.append(np.asarray(base, float))     # baseline always competes
        fine = []
        for q in shortlist:
            sc = self._fine_score(c, q, poly, next_task)
            if sc is not None and np.isfinite(sc):
                fine.append((sc, q))
        if not fine:
            return None, None, None
        fine.sort(key=lambda t: t[0])
        j_base = next((sc for sc, q in fine
                       if base is not None and float(np.linalg.norm(q - np.asarray(base, float))) < .1), None)
        rejected = fine[1:]
        return fine[0][1], j_base, rejected

    # ---- entry point ---------------------------------------------------
    def next_measure(self, c, poly, center, radius):
        self.diagnostics['lookahead_calls'] += 1
        if self.lookahead_mode == 'base' or radius > self.lookahead_radius:
            return self._base_pick(c, poly, center, radius)
        self.diagnostics['lookahead_active'] += 1
        base = self._base_pick(c, poly, center, radius)
        try:
            best, j_base, rejected = self._score_candidates(
                c, poly, center, radius, self._lookahead_candidates(c, poly, center, radius))
        except (ValueError, ArithmeticError, FloatingPointError, IndexError):
            self.diagnostics['lookahead_numeric_aborts'] += 1
            return base
        if best is None or not np.all(np.isfinite(best)):
            return base
        picked = best
        if base is not None and float(np.linalg.norm(picked - np.asarray(base, float))) < .1:
            picked = base
        self.diagnostics['lookahead_picks'].append(np.asarray(picked, float).tolist())
        if j_base is not None:
            j_best = self._fine_score(c, picked, poly, self._next_task_point(c))
            adopted = 0.
            if j_best is not None and np.isfinite(j_best):
                adopted = float(j_base - j_best)
                self.diagnostics['lookahead_pred_adopted_s'] += adopted
                self.diagnostics['lookahead_pred_calls'] += 1
                all_scores = [j_best] + [sc for sc, q in (rejected or [])
                                         if float(np.linalg.norm(np.asarray(q, float) - picked)) > .1]
                self.diagnostics['lookahead_pred_all_sum_s'] += float(np.sum(all_scores))
                self.diagnostics['lookahead_pred_all_n'] += len(all_scores)
            rej_savings = [float(j_base - sc) for sc, q in (rejected or [])
                           if float(np.linalg.norm(np.asarray(q, float) - picked)) > .1]
            rejected_saving = 0.
            if rej_savings:
                rejected_saving = max(rej_savings)
                self.diagnostics['lookahead_pred_rejected_max_s'] += rejected_saving
                self.diagnostics['lookahead_pred_rejected_calls'] += 1
            self.diagnostics['lookahead_pred_log'].append({'adopted_saving_s': adopted,
                                                          'rejected_saving_s': rejected_saving})
        if base is not None and float(np.linalg.norm(picked - np.asarray(base, float))) > .1:
            self.diagnostics['lookahead_changed'] += 1
        return picked

    def _lookahead_candidates(self, c, poly, center, radius):
        base = self._base_pick(c, poly, center, radius)
        cands = []
        if base is not None:
            cands.append(np.asarray(base, float))
        cands.append(self.pos.copy())
        samples = np.vstack([poly * .8 + center * .2, center[None, :]])
        if len(samples) > 4:
            samples = samples[np.linspace(0, len(samples) - 1, 4, dtype=int)]
        cands.extend(np.asarray(samples, float))
        nxt = self._next_task_point(c)
        if nxt is not None:
            d = np.asarray(nxt, float) - self.pos
            n = float(np.linalg.norm(d))
            if n > 1e-6:
                cands.append(self.pos + min(150., n) * d / n)
        out = []
        for q in cands:
            q = np.asarray(q, float)
            if any(np.linalg.norm(q - p) < .1 for p in self.measured[c]):
                continue
            out.append(q)
        if len(out) > self.lookahead_max_candidates:
            order = np.argsort([float(np.linalg.norm(q - self.pos)) for q in out])
            out = [out[i] for i in order[:self.lookahead_max_candidates]]
        return out


class JointLookahead(JointSearchSolver, LookaheadMixin):
    def _base_pick(self, c, poly, center, radius):
        return ActiveLocalizationSolver.next_measure(self, c, poly, center, radius)

    def __init__(self, *args, lookahead_radius=400., lam=.5, mode='service', continue_depth=2, **kwargs):
        JointSearchSolver.__init__(self, *args, **kwargs)
        self._setup_lookahead(lookahead_radius=lookahead_radius, lam=lam, mode=mode,
                              continue_depth=continue_depth)

    def next_measure(self, c, poly, center, radius):
        return LookaheadMixin.next_measure(self, c, poly, center, radius)

    def directional_options(self, c, poly, center, radius):
        opts = ActiveLocalizationSolver.directional_options(self, c, poly, center, radius)
        if self.lookahead_mode == 'base' or radius > self.lookahead_radius or not opts:
            return opts
        self.diagnostics['lookahead_active'] += 1
        best, _j_base, _rej = self._score_candidates(c, poly, center, radius, list(opts))
        if best is None:
            return opts
        return [best] + [np.asarray(q, float) for q in opts
                         if float(np.linalg.norm(np.asarray(q, float) - best)) > .1]
