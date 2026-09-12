"""Direct invariant tests for the revised short-lookahead (round 5).

Covers the specific defects reported and fixed:
  * coarse scores only shortlist; the final ranking is on one common (fine) scale,
    and the strong-baseline action always competes;
  * branch compression never drops no_signal / near, and infeasible branches are
    not invented;
  * the assumed continuation state advances position/channel/observations/measured
    points without touching the real controller and without resampling noise.
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / 'research' / 'iterative_speed'))

from lookahead import _HypState, _inside_convex  # noqa: E402
from variants import VARIANTS  # noqa: E402

KW = {'ring_radius': 1123., 'guard_initial': True, 'close_known': True,
      'skip_known_radius': 1200., 'probe_radius': 60., 'mode': 'service'}


def make_solver():
    cls, kwargs = VARIANTS[3]['la_q3_service']
    return cls(None, 3, **dict(KW, **kwargs))


class RankingTests(unittest.TestCase):
    def test_fine_scores_decide_not_coarse(self):
        """coarse [1, 2] with fine [100, 3] must select the second candidate."""
        solver = make_solver()
        poly = np.array([[0., 0.], [40., 0.], [40., 40.], [0., 40.]])
        center = poly.mean(axis=0)
        c1 = np.array([5., 5.])
        c2 = np.array([-5., -5.])
        solver._next_task_point = lambda c: None
        solver._base_pick = lambda *a: c2            # baseline action = candidate 2
        solver._coarse_score = lambda c, q, p, nt: 1. if np.allclose(q, c1) else 2.
        solver._fine_score = lambda c, q, p, nt: 100. if np.allclose(q, c1) else 3.
        best, j_base, rejected = solver._score_candidates(1, poly, center, 10., [c1, c2])
        self.assertTrue(np.allclose(best, c2), 'fine score must decide the final ranking')
        self.assertIsNotNone(j_base)

    def test_baseline_action_always_reaches_the_final_comparison(self):
        solver = make_solver()
        poly = np.array([[0., 0.], [40., 0.], [40., 40.], [0., 40.]])
        center = poly.mean(axis=0)
        base = np.array([1., 1.])
        others = [np.array([2., 2.]), np.array([3., 3.]), np.array([4., 4.]), np.array([5., 5.])]
        coarse_scores = {id(base): 99., id(others[0]): 1., id(others[1]): 2., id(others[2]): 3., id(others[3]): 4.}
        solver._next_task_point = lambda c: None
        solver._base_pick = lambda *a: base
        solver._coarse_score = lambda c, q, p, nt: coarse_scores.get(id(q), 50.)
        solver._fine_score = lambda c, q, p, nt: 0. if np.allclose(q, base) else 10.
        best, j_base, _ = solver._score_candidates(1, poly, center, 10., [base] + others)
        self.assertTrue(np.allclose(best, base), 'baseline must be shortlisted and win on fine scores')


class BranchTests(unittest.TestCase):
    def setUp(self):
        self.solver = make_solver()
        self.poly = np.array([[0., 0.], [60., 0.], [60., 60.], [0., 60.]])

    def test_compression_keeps_no_signal_and_near(self):
        q = np.array([30., 30.])
        branches = self.solver._branches(1, q, self.poly)
        kinds = {k for _, _, k in branches}
        self.assertIn('no_signal', kinds)
        self.assertIn('near', kinds)
        self.solver.lookahead_max_branches = 3
        compressed = self.solver._compress(branches)
        kept = {k for _, _, k in compressed}
        self.assertIn('no_signal', kept, 'compression must not drop no_signal')
        self.assertIn('near', kept, 'compression must not drop near')
        self.assertIn('direction', kept)
        self.assertLessEqual(len(compressed), 3 + 0)

    def test_near_is_not_invented_for_an_infeasible_point(self):
        far = np.array([500., 500.])
        kinds = {k for _, _, k in self.solver._branches(1, far, self.poly)}
        self.assertNotIn('near', kinds, 'near cannot occur when q is far from the posterior')

    def test_point_in_convex(self):
        self.assertTrue(_inside_convex(self.poly, np.array([30., 30.])))
        self.assertFalse(_inside_convex(self.poly, np.array([100., 30.])))


class AssumedStateTests(unittest.TestCase):
    def test_assumed_state_advances_without_touching_the_controller(self):
        solver = make_solver()
        solver.obs[1] = [(np.array([0., 0.]), 0.)]
        solver.measured[1] = [np.array([0., 0.])]
        solver.pos = np.array([0., 0.])
        before = (solver.pos.copy(), solver.channel, len(solver.obs[1]), len(solver.measured[1]))
        state = solver._assumed_state(1, np.array([10., 0.]))
        nxt, poly = solver._advance(state, 1, np.array([10., 0.]),
                                    np.array([[5., 0.], [15., 0.], [10., 10.]]), 'direction')
        self.assertEqual(nxt.pos.tolist(), [10., 0.])
        self.assertEqual(len(nxt.obs[1]), 2, 'assumed observation must be appended to the copy')
        self.assertEqual(len(nxt.measured[1]), 2)
        self.assertEqual(before[0].tolist(), solver.pos.tolist())
        self.assertEqual(before[1], solver.channel)
        self.assertEqual(before[2], len(solver.obs[1]), 'real observations must not be mutated')
        self.assertEqual(before[3], len(solver.measured[1]), 'real measured set must not be mutated')

    def test_no_signal_branch_keeps_the_polygon_and_records_no_bearing(self):
        solver = make_solver()
        solver.obs[1] = [(np.array([0., 0.]), 0.)]
        solver.measured[1] = [np.array([0., 0.])]
        poly = np.array([[0., 0.], [40., 0.], [40., 40.], [0., 40.]])
        state = solver._assumed_state(1, np.array([10., 10.]))
        nxt, npoly = solver._advance(state, 1, np.array([10., 10.]), poly, 'no_signal')
        self.assertEqual(len(nxt.obs[1]), 1, 'no_signal adds no bearing')
        self.assertEqual(len(nxt.measured[1]), 2, 'but the measured position is recorded')
        self.assertTrue(np.allclose(npoly, poly), 'the posterior is unchanged by no_signal')

    def test_continuation_scales_with_distance(self):
        """Cost must be charged per metre (unit sanity), not per candidate index."""
        solver = make_solver()
        solver.obs[1] = [(np.array([0., 0.]), 0.)]
        solver.measured[1] = [np.array([0., 0.])]
        poly = np.array([[0., 0.], [20., 0.], [20., 20.], [0., 20.]])
        near = solver._continue_cost(solver._assumed_state(1, np.array([20., 0.])), 1, poly,
                                     np.array([10., 10.]), 8., None, 0)
        far = solver._continue_cost(solver._assumed_state(1, np.array([200., 0.])), 1, poly,
                                    np.array([10., 10.]), 8., None, 0)
        self.assertGreater(far, near + 10., 'a 180 m longer walk must cost ~36 s more')


class PredictionUnitTests(unittest.TestCase):
    def _rows(self):
        return [
            {'seed': 1, 'variant': 'ctl', 'score_time_s': 10., 'virtual_time_s': 100.},
            {'seed': 1, 'variant': 'arm', 'score_time_s': 5., 'virtual_time_s': 60.,
             'lookahead_pred_adopted_s': 25., 'lookahead_pred_rejected_max_s': 5.,
             'lookahead_pred_all_sum_s': 300., 'lookahead_pred_all_n': 10,
             'lookahead_pred_calls': 3, 'lookahead_pred_rejected_calls': 2},
        ]

    def test_realised_effect_uses_scene_seconds_not_per_source(self):
        import analyze_prediction as ap
        out, _ctl, _cand = ap.compute(self._rows(), 'ctl', 'arm', 'lookahead')
        # scene seconds: 100 - 60 = 40, NOT the per-source 10 - 5 = 5
        self.assertAlmostEqual(out['scene_realised_saving_s'], 40.)

    def test_buckets_are_reported_separately_and_never_summed(self):
        import analyze_prediction as ap
        out, _ctl, _cand = ap.compute(self._rows(), 'ctl', 'arm', 'lookahead')
        b = out['buckets']
        self.assertAlmostEqual(b['adopted_predicted_saving_s'], 25.)
        self.assertAlmostEqual(b['rejected_best_predicted_saving_s'], 5.)
        self.assertAlmostEqual(b['all_candidates_mean_predicted_cost_s'], 30.)   # 300/10
        self.assertNotAlmostEqual(out['scene_realised_saving_s'],
                                  b['adopted_predicted_saving_s'],
                                  msg='decision-level prediction must not be equated with the scene gain')
        self.assertIn('decision-level', out['note'])
        self.assertEqual(out['units']['realised'], 's (scene total, virtual_time_s difference)')

    def test_development_only_marker_is_present(self):
        import analyze_prediction as ap
        out, _ctl, _cand = ap.compute(self._rows(), 'ctl', 'arm', 'lookahead')
        self.assertIn('development_only', out['use'])


class PredictionBucketTests(unittest.TestCase):
    def test_threshold_style_prediction_is_not_accumulated_as_a_scene_gain(self):
        solver = make_solver()
        self.assertIn('lookahead_pred_log', solver.diagnostics)
        for key in ('lookahead_pred_adopted_s', 'lookahead_pred_rejected_max_s',
                    'lookahead_pred_all_sum_s', 'lookahead_pred_all_n'):
            self.assertIn(key, solver.diagnostics)


if __name__ == '__main__':
    unittest.main()
