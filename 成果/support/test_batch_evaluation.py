"""Batch evaluation smoke test: one seed per problem, summary shape only."""
import unittest

import batch_evaluation as batch


class BatchEvaluationTests(unittest.TestCase):
    def test_single_seed_runs_complete_and_summarize(self):
        for problem, start in ((3, 3000000), (4, 3100000)):
            row = batch.run_one(start, problem, 'default')
            self.assertEqual(row['cleared'], row['sources'])
            self.assertTrue(row['normal_exit'])
            self.assertGreater(row['mean_time_s'], 0.)
            summary = batch.summarize([row], problem)
            dist = summary['arms']['default']['distribution_mean_time_s']
            self.assertEqual(dist['n'], 1)
            self.assertGreater(dist['mean'], 0.)
            self.assertEqual(summary['reference'], 'default')


if __name__ == '__main__':
    unittest.main()
