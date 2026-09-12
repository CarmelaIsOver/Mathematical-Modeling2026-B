"""Q4 step-rescheduling primitives: budget accumulation and non-repetition."""
import unittest
from unittest.mock import patch

import numpy as np

from joint_search import JointSearchSolver
from active_localization import ActiveLocalizationSolver


class RescheduleDefaultTests(unittest.TestCase):
    def test_default_arm_is_the_untouched_joint_scheduler(self):
        solver = JointSearchSolver(None, 4)
        self.assertFalse(solver.reschedule_after_step)
        self.assertFalse(solver.step_skip_known)
        self.assertEqual(solver.target_measures, {})
        self.assertEqual(solver.small_probe_state, {})


class RescheduleBudgetTests(unittest.TestCase):
    def _solver(self, budget):
        return JointSearchSolver(None, 4, reschedule_after_step=True,
                                 target_measure_budget=budget)

    def test_budget_accumulates_across_rescheduling(self):
        solver = self._solver(2)
        with patch.object(solver, '_small_region_probe', return_value=False), \
             patch.object(solver, 'directional_step', return_value='open'), \
             patch.object(solver, 'directional_fallback') as fallback:
            solver.locate(7)
            solver.locate(7)
            self.assertEqual(solver.target_measures[7], 2)
            fallback.assert_not_called()
            solver.locate(7)  # budget spent: one uninterrupted fallback
            fallback.assert_called_once_with(7)
            self.assertEqual(solver.diagnostics['reschedule_fallbacks'], 1)

    def test_no_progress_falls_back_immediately(self):
        solver = self._solver(8)
        with patch.object(solver, '_small_region_probe', return_value=False), \
             patch.object(solver, 'directional_step', return_value='no_progress'), \
             patch.object(solver, 'directional_fallback') as fallback:
            solver.locate(7)
            fallback.assert_called_once_with(7)

    def test_cleared_step_does_not_fall_back(self):
        solver = self._solver(8)
        with patch.object(solver, '_small_region_probe', return_value=False), \
             patch.object(solver, 'directional_step', return_value='cleared'), \
             patch.object(solver, 'directional_fallback') as fallback:
            self.assertIsNone(solver.locate(7))
            fallback.assert_not_called()
            self.assertEqual(solver.target_measures[7], 1)


class SmallProbeTests(unittest.TestCase):
    def test_failed_probe_is_not_repeated_for_the_same_region_state(self):
        solver = JointSearchSolver(None, 4, reschedule_after_step=True)
        with patch.object(solver, 'region', return_value=(None, np.zeros(2), 30.)), \
             patch.object(solver, 'clear', return_value=False):
            self.assertFalse(solver._small_region_probe(7))
            self.assertFalse(solver._small_region_probe(7))
        self.assertEqual(solver.diagnostics['small_region_probes'], 1)

    def test_probe_repeats_after_new_observations(self):
        solver = JointSearchSolver(None, 4, reschedule_after_step=True)
        with patch.object(solver, 'region', return_value=(None, np.zeros(2), 30.)), \
             patch.object(solver, 'clear', return_value=False):
            solver._small_region_probe(7)
            solver.obs[7].append((np.zeros(2), 0.))  # new positive observation
            solver._small_region_probe(7)
        self.assertEqual(solver.diagnostics['small_region_probes'], 2)


class DirectionalPrimitiveTests(unittest.TestCase):
    def test_options_are_shared_and_ordered_by_distance(self):
        solver = ActiveLocalizationSolver(None, 4)
        solver.obs[3].append((np.array([500., 0.]), 0.))
        center = np.array([600., 0.])
        with patch.object(solver, 'next_measure', return_value=np.array([400., 40.])):
            options = solver.directional_options(3, None, center, 100.)
        self.assertEqual(len(options), 3)
        self.assertTrue(np.allclose(options[0], [400., 40.]))
        distances = [np.linalg.norm(p - solver.pos) for p in options]
        self.assertEqual(distances, sorted(distances))


if __name__ == '__main__':
    unittest.main()
