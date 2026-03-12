from io import StringIO
import json
import tempfile

from django.core.management import call_command
from django.test import TestCase

from customer_request_policy import _merge_candidates
from messaging.feedback_scores import rebuild_feedback_scores
from messaging.models import CustomerRequestLearningSummary, PageKeyFeedbackScore


class FeedbackScoreRebuildTests(TestCase):
    def test_rebuild_feedback_scores_aggregates_learning_summaries(self):
        CustomerRequestLearningSummary.objects.create(
            request_id='rid-1',
            label_quality='medium',
            summary={
                'predicted_primary_page': 'service_selection',
                'model_feedback_value': 'thumbs_up',
                'positive_labels': ['service_selection'],
                'negative_labels': [],
            },
        )
        CustomerRequestLearningSummary.objects.create(
            request_id='rid-2',
            label_quality='medium',
            summary={
                'predicted_primary_page': 'moving_date',
                'model_feedback_value': 'thumbs_down',
                'positive_labels': [],
                'negative_labels': ['moving_date'],
            },
        )

        result = rebuild_feedback_scores()

        self.assertEqual(result.get('updated'), 2)
        good = PageKeyFeedbackScore.objects.get(page_key='service_selection')
        bad = PageKeyFeedbackScore.objects.get(page_key='moving_date')

        self.assertEqual(good.thumbs_up_count, 1)
        self.assertEqual(good.positive_label_count, 1)
        self.assertGreater(good.score_boost, 0)

        self.assertEqual(bad.thumbs_down_count, 1)
        self.assertEqual(bad.negative_label_count, 1)
        self.assertLess(bad.score_boost, 0)


class FeedbackBoostRankingTests(TestCase):
    def test_merge_candidates_applies_feedback_boost(self):
        heuristic = [
            {'page_key': 'A', 'score': 0.60, 'source': 'heuristic'},
            {'page_key': 'B', 'score': 0.59, 'source': 'heuristic'},
        ]
        merged = _merge_candidates(
            heuristic,
            [],
            top_k=2,
            feedback_boosts={'A': -1.0, 'B': 1.0},
        )

        self.assertEqual(merged[0]['page_key'], 'B')
        self.assertEqual(merged[1]['page_key'], 'A')


class RebuildFeedbackScoresCommandTests(TestCase):
    def test_command_runs_and_prints_summary(self):
        CustomerRequestLearningSummary.objects.create(
            request_id='rid-cmd-1',
            label_quality='medium',
            summary={
                'predicted_primary_page': 'service_selection',
                'model_feedback_value': 'thumbs_up',
                'positive_labels': ['service_selection'],
                'negative_labels': [],
            },
        )

        out = StringIO()
        call_command('rebuild_feedback_scores', top=1, stdout=out)
        output = out.getvalue()

        self.assertIn('feedback score rebuild done: updated=1', output)
        self.assertIn('service_selection', output)

    def test_command_exports_learning_dataset_json(self):
        CustomerRequestLearningSummary.objects.create(
            request_id='rid-export-1',
            label_quality='strong',
            summary={
                'user_message': '서비스를 바꾸고 싶어요',
                'predicted_primary_page': 'service_selection',
                'positive_labels': ['service_selection'],
                'negative_labels': [],
                'actual_edit_page': 'service_selection',
            },
        )

        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as fp:
            export_path = fp.name

        out = StringIO()
        call_command('rebuild_feedback_scores', top=0, export=export_path, min_quality='strong', stdout=out)
        output = out.getvalue()

        self.assertIn('learning dataset exported: count=1', output)
        with open(export_path, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['request_id'], 'rid-export-1')
