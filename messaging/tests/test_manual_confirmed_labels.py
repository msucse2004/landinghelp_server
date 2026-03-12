from django.test import TestCase

from messaging.feedback_scores import rebuild_feedback_scores
import json
import tempfile

from messaging.feedback_scores import export_learning_dataset, rebuild_feedback_scores
from messaging.models import (
    CustomerRequestLearningSummary,
    CustomerRequestManualLabelRevision,
    PageKeyFeedbackScore,
)


class ManualConfirmedLabelModelTests(TestCase):
    def test_label_source_auto_and_manual(self):
        row = CustomerRequestLearningSummary.objects.create(
            request_id='manual-label-source-1',
            label_quality='strong',
            summary={
                'positive_labels': ['auto_page'],
            },
        )
        self.assertEqual(row.label_source, 'auto')
        self.assertEqual(row.get_effective_page_keys(), ['auto_page'])

        row.manual_confirmed_page_key = 'manual_page'
        row.save(update_fields=['manual_confirmed_page_key'])
        row.refresh_from_db()
        self.assertEqual(row.label_source, 'manual')
        self.assertEqual(row.get_effective_page_keys(), ['manual_page'])


class ManualConfirmedLabelScoringTests(TestCase):
    def test_rebuild_feedback_scores_prefers_manual_page_key(self):
        CustomerRequestLearningSummary.objects.create(
            request_id='manual-label-score-1',
            label_quality='strong',
            manual_confirmed_page_key='manual_service_selection',
            summary={
                'predicted_primary_page': 'predicted_page',
                'positive_labels': ['auto_page_should_not_win'],
                'negative_labels': [],
                'model_feedback_value': '',
            },
        )

        rebuild_feedback_scores()

        manual = PageKeyFeedbackScore.objects.filter(page_key='manual_service_selection').first()
        auto = PageKeyFeedbackScore.objects.filter(page_key='auto_page_should_not_win').first()
        self.assertIsNotNone(manual)
        self.assertIsNotNone(auto)
        self.assertGreaterEqual(auto.negative_label_count, 1)

    def test_revision_before_after_reflected_in_scoring_and_export(self):
        row = CustomerRequestLearningSummary.objects.create(
            request_id='manual-revision-1',
            label_quality='strong',
            manual_confirmed_page_key='after_page',
            summary={
                'predicted_primary_page': 'predicted_page',
                'positive_labels': ['before_page'],
                'negative_labels': [],
                'model_feedback_value': '',
            },
        )
        CustomerRequestManualLabelRevision.objects.create(
            learning_summary=row,
            request_id=row.request_id,
            before_intent='SURVEY_REOPEN_REQUEST',
            after_intent='SURVEY_REOPEN_REQUEST',
            before_page_key='before_page',
            after_page_key='after_page',
            before_notes='before',
            after_notes='after',
        )

        rebuild_feedback_scores()

        before_score = PageKeyFeedbackScore.objects.filter(page_key='before_page').first()
        after_score = PageKeyFeedbackScore.objects.filter(page_key='after_page').first()
        self.assertIsNotNone(before_score)
        self.assertIsNotNone(after_score)
        self.assertGreaterEqual(after_score.positive_label_count, 1)
        self.assertGreaterEqual(before_score.negative_label_count, 1)

        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as fp:
            export_path = fp.name
        exported = export_learning_dataset(export_path, min_quality='strong')
        self.assertEqual(exported.get('count'), 1)
        with open(export_path, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
        self.assertEqual(len(data), 1)
        item = data[0]
        self.assertEqual(item['auto_positive_labels'], ['before_page'])
        self.assertEqual(item['positive_labels'], ['after_page'])
        self.assertEqual(item['manual_label_revisions'][0]['before_page_key'], 'before_page')
        self.assertEqual(item['manual_label_revisions'][0]['after_page_key'], 'after_page')
