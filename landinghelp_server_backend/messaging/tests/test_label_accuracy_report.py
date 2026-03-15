from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from messaging.learning_labels import build_manual_label_accuracy_report
from messaging.models import CustomerRequestIntentAnalysis, CustomerRequestLearningSummary


User = get_user_model()


class LabelAccuracyReportTests(TestCase):
    def test_build_manual_label_accuracy_report_counts_page_and_intent_mismatch(self):
        user = User.objects.create_user(username='label_report_user', email='label_report@test.com', password='p')

        CustomerRequestLearningSummary.objects.create(
            request_id='rid-report-1',
            label_quality='strong',
            manual_confirmed_intent='SURVEY_REOPEN_REQUEST',
            manual_confirmed_page_key='service_selection',
            summary={
                'predicted_primary_page': 'entry_purpose_stay',
            },
        )
        CustomerRequestIntentAnalysis.objects.create(
            customer=user,
            original_text='x',
            predicted_intent='SCHEDULE_CHANGE_REQUEST',
            predicted_action='ROUTE_TO_AGENT_REVIEW',
            execution_mode='HUMAN_REVIEW_REQUIRED',
            confidence=0.8,
            source='heuristic',
            request_id='rid-report-1',
        )

        CustomerRequestLearningSummary.objects.create(
            request_id='rid-report-2',
            label_quality='strong',
            manual_confirmed_intent='SURVEY_REOPEN_REQUEST',
            manual_confirmed_page_key='service_selection',
            summary={
                'predicted_primary_page': 'service_selection',
            },
        )
        CustomerRequestIntentAnalysis.objects.create(
            customer=user,
            original_text='y',
            predicted_intent='SURVEY_REOPEN_REQUEST',
            predicted_action='OFFER_SURVEY_REOPEN',
            execution_mode='AUTO_CONFIRMABLE',
            confidence=0.9,
            source='semantic_safe',
            request_id='rid-report-2',
        )

        report = build_manual_label_accuracy_report(limit=10)

        self.assertEqual(report['total_manual_labeled'], 2)
        self.assertEqual(report['page_mismatch_count'], 1)
        self.assertEqual(report['intent_mismatch_count'], 1)
        self.assertEqual(report['top_wrong_predicted_pages'][0]['predicted_page_key'], 'entry_purpose_stay')
        self.assertEqual(report['top_wrong_predicted_intents'][0]['predicted_intent'], 'SCHEDULE_CHANGE_REQUEST')
        self.assertEqual(report['top_page_mismatch_pairs'][0]['manual_page_key'], 'service_selection')
        self.assertEqual(report['top_intent_mismatch_pairs'][0]['manual_intent'], 'SURVEY_REOPEN_REQUEST')

    def test_build_manual_label_accuracy_report_with_days_filter(self):
        old_row = CustomerRequestLearningSummary.objects.create(
            request_id='rid-report-old',
            label_quality='strong',
            manual_confirmed_intent='SURVEY_REOPEN_REQUEST',
            manual_confirmed_page_key='service_selection',
            summary={'predicted_primary_page': 'entry_purpose_stay'},
        )
        CustomerRequestLearningSummary.objects.filter(pk=old_row.pk).update(
            updated_at=timezone.now() - timedelta(days=45)
        )

        CustomerRequestLearningSummary.objects.create(
            request_id='rid-report-new',
            label_quality='strong',
            manual_confirmed_intent='SURVEY_REOPEN_REQUEST',
            manual_confirmed_page_key='service_selection',
            summary={'predicted_primary_page': 'entry_purpose_stay'},
        )

        report_all = build_manual_label_accuracy_report(limit=10)
        report_30 = build_manual_label_accuracy_report(limit=10, days=30)

        self.assertEqual(report_all['total_manual_labeled'], 2)
        self.assertEqual(report_30['total_manual_labeled'], 1)
        self.assertEqual(report_30['period_days'], 30)
