"""Direction A: complete-service-cost short lookahead for localization picks.

J(a) = real move/action cost of a
     + E_branch[ certified-clear leg from a + exit leg to the next retained task ]
     + lam * ( worst-branch cost - mean-branch cost )

Branches are the bounded bearing bins from ``outcomes`` (equal-weight planning
assumption, never a probability claim about the true source). All costs are charged
as the backend does: 1 s per 5 m, 5 s per measure, 1 s per channel switch,
3 s optical + 2 s laser per successful clear.

``mode``
  base       -> untouched base policy (strong-baseline control)
  cand_paper -> extended candidate set, old max-gap style score (isolates the value
                of the candidate set alone)
  service    -> extended candidates plus the full service-cost model above
"""
import numpy as np

from active_localization import ActiveLocalizationSolver, outcomes, radius_bound
from joint_search import JointSearchSolver
from omni_search import OmniSearchSolver
from solver import Solver, safe_clear_point


class LookaheadMixin:
    def _setup_lookahead(self, lookahead_radius=400., lam=.5, max_candidates=12,
                         max_branches=8, mode='service'):
        self.lookahead_radius = float(lookahead_radius)
        self.lookahead_lam = float(lam)
        self.lookahead_max_candidates = int(max_candidates)
        self.lookahead_max_branches = int(max_branches)
        self.lookahead_mode = mode
        self.diagnostics.update(lookahead_calls=0, lookahead_active=0, lookahead_changed=0,
                                lookahead_branches=0)

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

    def _branch_cost(self, q, post, c, next_task, kind='direction'):
        """Charged cost from q to a cleared channel plus the exit leg, one branch."""
        rb, mb = radius_bound(post)
        if kind == 'no_signal':
            q2 = self._base_pick(c, post, mb, rb)
            if q2 is None:
                return float(np.linalg.norm(q - mb)) / 5 + 5. + float(rb) / 5
            _, end, _, tail = self._terminal_estimate(c, post, q2)
            leg = float(np.linalg.norm(q - q2)) / 5 + 5. + int(c != self.channel) + tail
            exit_s = 0. if next_task is None else float(np.linalg.norm(end - np.asarray(next_task, float))) / 5
            return leg + exit_s
        if rb <= 19.99:
            cp = np.asarray(safe_clear_point(q, mb, rb), float)
            leg = float(np.linalg.norm(q - cp)) / 5 + 5.
            end = cp
        else:
            q2 = Solver.next_measure(self, c, post, mb, rb)
            if q2 is None:
                leg = float(np.linalg.norm(q - mb)) / 5 + 5. + float(rb) / 5
                end = np.asarray(mb, float)
            else:
                _, end, _, tail = self._terminal_estimate(c, post, q2)
                leg = float(np.linalg.norm(q - q2)) / 5 + 5. + int(c != self.channel) + tail
        exit_s = 0. if next_task is None else float(np.linalg.norm(end - np.asarray(next_task, float))) / 5
        return leg + exit_s

    def _terminal_estimate(self, c, post, q2):
        """Terminal estimate on a hypothesised posterior: baseline rule plus clear leg."""
        branches = outcomes(post, q2, bins=8)
        if branches:
            rb2, mb2 = radius_bound(branches[0][0])
        else:
            rb2, mb2 = radius_bound(post)
        if rb2 <= 19.99:
            cp = np.asarray(safe_clear_point(q2, mb2, rb2), float)
            tail = float(np.linalg.norm(q2 - cp)) / 5 + 5.
            end = cp
        else:
            tail = float(np.linalg.norm(q2 - mb2)) / 5 + float(rb2) / 5
            end = np.asarray(mb2, float)
        return rb2, end, mb2, tail

    def _base_pick(self, c, poly, center, radius):
        """Strong-baseline measurement choice (overridden per problem)."""
        return Solver.next_measure(self, c, poly, center, radius)

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

    def _branches(self, c, q, poly, bins=12):
        """Bearing bins plus the non-progressing outcomes the spec requires.

        Planning assumption only: ``near`` and ``no_signal`` each get the weight of
        one bearing bin. They are not claimed to be equally probable; without a
        stated prior an equal-weight sample is the transparent choice, and the
        no_signal branch keeps its real cost (no region update, continuation from
        the unchanged polygon).
        """
        out = [(post, 1., 'direction') for post, _ in outcomes(poly, q, bins=bins)]
        out.append((poly, 1., 'no_signal'))
        return out

    def _coarse_score(self, c, q, poly, next_task):
        """Cheap one-ply score: no nested baseline continuation."""
        branches = self._branches(c, q, poly)
        if not branches:
            return None
        if len(branches) > self.lookahead_max_branches:
            idx = np.linspace(0, len(branches) - 1, self.lookahead_max_branches, dtype=int)
            branches = [branches[i] for i in idx]
        self.diagnostics['lookahead_branches'] += len(branches)
        action = float(np.linalg.norm(q - self.pos)) / 5 + 5. + int(c != self.channel)
        near_dist = float(np.linalg.norm(q - self.pos))
        costs = []
        for post, _w, kind in branches:
            rb, mb = radius_bound(post)
            if kind == 'no_signal':
                costs.append(float(np.linalg.norm(q - mb)) / 5 + 5. + float(rb) / 5
                             + (0. if next_task is None
                                else float(np.linalg.norm(mb - np.asarray(next_task, float))) / 5))
                continue
            if rb <= 19.99:
                cp = np.asarray(safe_clear_point(q, mb, rb), float)
                leg = float(np.linalg.norm(q - cp)) / 5 + 5.
                end = cp
            else:
                leg = float(np.linalg.norm(q - mb)) / 5 + 5. + float(rb) / 5
                end = np.asarray(mb, float)
            exit_s = 0. if next_task is None else float(np.linalg.norm(end - np.asarray(next_task, float))) / 5
            costs.append(leg + exit_s)
        costs = np.asarray(costs, float)
        if self.lookahead_mode == 'cand_paper':
            return action + float(costs.max())
        return action + float(costs.mean()) + self.lookahead_lam * float(costs.max() - costs.mean())

    def _fine_score(self, c, q, poly, next_task):
        """Two-ply score: non-certified branches continue with the baseline rule."""
        branches = self._branches(c, q, poly)
        if not branches:
            return None
        if len(branches) > self.lookahead_max_branches:
            idx = np.linspace(0, len(branches) - 1, self.lookahead_max_branches, dtype=int)
            branches = [branches[i] for i in idx]
        action = float(np.linalg.norm(q - self.pos)) / 5 + 5. + int(c != self.channel)
        costs = np.asarray([self._branch_cost(q, post, c, next_task, kind) for post, _w, kind in branches], float)
        if self.lookahead_mode == 'cand_paper':
            return action + float(costs.max())
        return action + float(costs.mean()) + self.lookahead_lam * float(costs.max() - costs.mean())

    def _score_candidates(self, c, poly, radius, cands, fine_top=3):
        next_task = self._next_task_point(c)
        scored = []
        for q in cands:
            sc = self._coarse_score(c, q, poly, next_task)
            if sc is not None:
                scored.append((sc, q))
        if not scored:
            return None
        scored.sort(key=lambda t: t[0])
        best_q = scored[0][1]
        for _, q in scored[:fine_top]:
            sc = self._fine_score(c, q, poly, next_task)
            if sc is not None and sc < scored[0][0]:
                scored[0] = (sc, q)
        best_q = min(scored, key=lambda t: t[0])[1]
        return best_q

    def next_measure(self, c, poly, center, radius):
        self.diagnostics['lookahead_calls'] += 1
        if self.lookahead_mode == 'base' or radius > self.lookahead_radius:
            return self._base_pick(c, poly, center, radius)
        self.diagnostics['lookahead_active'] += 1
        base = self._base_pick(c, poly, center, radius)
        best = self._score_candidates(c, poly, radius, self._lookahead_candidates(c, poly, center, radius))
        if best is None:
            return base
        if base is not None and float(np.linalg.norm(best - base)) > .1:
            self.diagnostics['lookahead_changed'] += 1
        return best


class JointLookahead(JointSearchSolver, LookaheadMixin):
    def _base_pick(self, c, poly, center, radius):
        return ActiveLocalizationSolver.next_measure(self, c, poly, center, radius)

    def __init__(self, *args, lookahead_radius=400., lam=.5, mode='service', **kwargs):
        JointSearchSolver.__init__(self, *args, **kwargs)
        self._setup_lookahead(lookahead_radius=lookahead_radius, lam=lam, mode=mode)

    def next_measure(self, c, poly, center, radius):
        return LookaheadMixin.next_measure(self, c, poly, center, radius)

    def directional_options(self, c, poly, center, radius):
        opts = ActiveLocalizationSolver.directional_options(self, c, poly, center, radius)
        if self.lookahead_mode == 'base' or radius > self.lookahead_radius or not opts:
            return opts
        self.diagnostics['lookahead_active'] += 1
        best = self._score_candidates(c, poly, radius, list(opts))
        if best is None:
            return opts
        out = [best] + [np.asarray(q, float) for q in opts
                        if float(np.linalg.norm(np.asarray(q, float) - best)) > .1]
        return out
