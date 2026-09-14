import unittest
from unittest.mock import Mock, patch

from ai_core.agents.researcher import collect_snapshot
from ai_core.agents.supervisor import reconcile_availability


class CollectionCompletenessTests(unittest.TestCase):
    def test_empty_bounded_feed_does_not_hide_previous_jobs(self):
        for provider in ('dice', 'jobicy', 'remotive'):
            with self.subTest(provider=provider), patch('ai_core.agents.researcher.collect', return_value=[]):
                snapshot = collect_snapshot({'provider': provider})
                conn = Mock()
                reconcile_availability(conn, {'source_id': 's', 'created_at': 't'}, snapshot)
                conn.execute.assert_not_called()

    def test_complete_empty_board_reconciles_only_its_source(self):
        for provider in ('ashby', 'greenhouse', 'lever'):
            with self.subTest(provider=provider), patch('ai_core.agents.researcher.collect', return_value=[]):
                snapshot = collect_snapshot({'provider': provider})
                conn = Mock()
                reconcile_availability(conn, {'source_id': 's', 'created_at': 't'}, snapshot)
                conn.execute.assert_called_once()
                self.assertEqual(conn.execute.call_args.args[1], ('s', 't'))

    def test_incomplete_pagination_propagates_failure(self):
        with patch('ai_core.agents.researcher.collect', side_effect=ValueError('Pagination limit exceeded')):
            with self.assertRaises(ValueError):
                collect_snapshot({'provider': 'lever'})

    def test_unknown_future_provider_cannot_establish_absence(self):
        with patch('ai_core.agents.researcher.collect', return_value=[{'source_job_id': '1'}]):
            snapshot = collect_snapshot({'provider': 'new-search'})
            self.assertFalse(snapshot.complete_board)
            self.assertEqual(len(snapshot.jobs), 1)


if __name__ == '__main__':
    unittest.main()
