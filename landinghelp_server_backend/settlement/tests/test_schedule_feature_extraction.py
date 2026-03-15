from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from settlement.models import ServiceScheduleItem, ServiceSchedulePlan
from settlement.schedule_features import (
    build_current_submission_feature_context,
    build_historical_schedule_feature_contexts,
    normalize_service_code_set,
)
from survey.models import SurveyQuestion, SurveySubmission


User = get_user_model()


class ScheduleFeatureExtractionTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='feature_customer',
            email='feature_customer@test.com',
            password='testpass123',
        )
        self._add_question('entry_date_feature', 'entry_date', 'date')
        self._add_question('settlement_state_feature', 'settlement_state', 'text')
        self._add_question('settlement_city_feature', 'settlement_city', 'text')
        self._add_question('household_adults_feature', 'household_adults', 'number')
        self._add_question('household_children_feature', 'household_children', 'number')
        self._add_question('entry_purpose_feature', 'entry_purpose', 'text')
        self._add_question('stay_status_feature', 'stay_status', 'options')
        self._add_question('stay_duration_feature', 'stay_duration', 'options')
        self._add_question('special_requirements_feature', 'special_requirements', 'options')

    def _add_question(self, key, mapping_key, value_type):
        SurveyQuestion.objects.create(
            key=key,
            label=key,
            field_type=SurveyQuestion.FieldType.TEXT,
            step=1,
            order=1,
            required=False,
            is_active=True,
            quote_relevant=True,
            quote_mapping_key=mapping_key,
            quote_value_type=value_type,
        )

    def _submission(self, user=None, *, entry_date='2026-09-20', state='NC', city='Morrisville'):
        target_user = user or self.customer
        return SurveySubmission.objects.create(
            user=target_user,
            email=target_user.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={
                'entry_date_feature': entry_date,
                'settlement_state_feature': state,
                'settlement_city_feature': city,
                'household_adults_feature': '2',
                'household_children_feature': '1',
                'entry_purpose_feature': 'work',
                'stay_status_feature': 'visa',
                'stay_duration_feature': '1 year',
                'special_requirements_feature': 'translator',
                'service_delivery_mode': 'per_service',
                'service_delivery_per_service': {
                    'SVC_A': 'agent_direct',
                    'SVC_B': 'ai_service',
                    'SVC_C': 'self_search',
                },
            },
            requested_required_services=['svc_a', 'SVC_B', '  svc_a  '],
            requested_optional_services=['svc_c'],
        )

    def test_current_submission_feature_extraction(self):
        submission = self._submission()

        features = build_current_submission_feature_context(
            submission,
            today=date(2026, 9, 1),
        )

        self.assertEqual(features['entry_date'].isoformat(), '2026-09-20')
        self.assertEqual(features['remaining_days_to_entry'], 19)
        self.assertEqual(features['expected_schedule_weeks'], 2.7)  # round(19/7, 1)
        self.assertEqual(features['state_code'], 'NC')
        self.assertEqual(features['city'], 'Morrisville')
        self.assertEqual(set(features['requested_service_codes']), {'SVC_A', 'SVC_B', 'SVC_C'})
        self.assertEqual(features['service_count'], 3)
        self.assertEqual(features['in_person_service_count'], 1)
        self.assertEqual(features['ai_service_count'], 1)
        self.assertEqual(features['self_search_service_count'], 1)
        self.assertEqual(features['household_size'], 3)
        self.assertEqual(features['entry_purpose'], 'work')

    def test_historical_schedule_feature_context_extraction(self):
        submission = self._submission(entry_date='2026-08-10', state='CA', city='Irvine')
        plan = ServiceSchedulePlan.objects.create(
            submission=submission,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.SENT,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=1,
        )
        starts_at = timezone.make_aware(timezone.datetime(2026, 8, 14, 10, 0, 0))
        ServiceScheduleItem.objects.create(
            schedule_plan=plan,
            service_code='SVC_A',
            service_label='Service A',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=1),
            duration_minutes=60,
            status=ServiceScheduleItem.ItemStatus.CONFIRMED,
        )

        rows = build_historical_schedule_feature_contexts(service_codes=['svc_a'], today=date(2026, 8, 1))

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['service_code'], 'SVC_A')
        self.assertEqual(row['state_code'], 'CA')
        self.assertEqual(row['city'], 'Irvine')
        self.assertEqual(row['days_from_entry'], 4)
        # historical row에는 entry_date(절대날짜)/remaining_days_to_entry(today 기준 음수)를 노출하지 않음
        self.assertNotIn('entry_date', row)
        self.assertNotIn('remaining_days_to_entry', row)
        # plan-level week span: 아이템 1개라 span 계산 불가 → 0.0
        self.assertEqual(row['schedule_week_span'], 0.0)
        # 담당 agent 미지정
        self.assertIsNone(row['assigned_agent_id'])

    def test_missing_field_fallback_behavior(self):
        submission_missing = self._submission(entry_date='', state='', city='')
        plan = ServiceSchedulePlan.objects.create(
            submission=submission_missing,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.SENT,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=1,
        )
        starts_at = timezone.now() + timedelta(days=2)
        ServiceScheduleItem.objects.create(
            schedule_plan=plan,
            service_code='SVC_A',
            service_label='Service A',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=1),
            duration_minutes=60,
            status=ServiceScheduleItem.ItemStatus.CONFIRMED,
        )

        rows = build_historical_schedule_feature_contexts(service_codes=['SVC_A'])
        self.assertEqual(rows, [])

        current = build_current_submission_feature_context(submission_missing)
        self.assertIsNone(current['entry_date'])
        self.assertIsNone(current['remaining_days_to_entry'])
        self.assertEqual(current['state_code'], '')
        self.assertEqual(current['city'], '')

    def test_consistent_service_set_normalization(self):
        normalized = normalize_service_code_set([' svc_a ', 'SVC_A', 'svc_b', 'SVC_C', 'svc_b'])
        self.assertEqual(normalized, ['SVC_A', 'SVC_B', 'SVC_C'])

    def test_feature_extraction_normalizes_option_lists_to_text(self):
        submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={
                'entry_date_feature': '2026-09-20',
                'settlement_state_feature': ['NC'],
                'settlement_city_feature': ['Morrisville'],
                'household_adults_feature': '2',
                'household_children_feature': '1',
                'entry_purpose_feature': ['work', 'family'],
                'stay_status_feature': ['visa', 'dependent'],
                'stay_duration_feature': ['1 year'],
                'special_requirements_feature': ['translator', 'wheelchair'],
                'preferred_agent_id': ['admin_assign'],
            },
            requested_required_services='svc_a',
            requested_optional_services=['svc_b'],
        )

        features = build_current_submission_feature_context(submission, today=date(2026, 9, 1))

        self.assertEqual(features['state_code'], 'NC')
        self.assertEqual(features['city'], 'Morrisville')
        self.assertEqual(features['entry_purpose'], 'work, family')
        self.assertEqual(features['stay_status'], 'visa, dependent')
        self.assertEqual(features['stay_duration'], '1 year')
        self.assertEqual(features['raw_special_requirements'], 'translator, wheelchair')
        self.assertTrue(features['has_special_requirements'])
        self.assertEqual(features['preferred_agent_id'], 'admin_assign')
        self.assertEqual(features['requested_service_codes'], ['SVC_A', 'SVC_B'])
