from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from settlement.models import ServiceScheduleItem, ServiceSchedulePlan
from settlement.scheduling_engine import (
    build_scheduling_context,
    generate_schedule_draft,
    recommend_schedule_placements,
)
from survey.models import SurveyQuestion, SurveySubmission


User = get_user_model()


class HistoricalRecommendationEngineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='hist_customer',
            email='hist_customer@test.com',
            password='testpass123',
        )
        SurveyQuestion.objects.create(
            key='entry_date_hist',
            label='입국일',
            field_type=SurveyQuestion.FieldType.TEXT,
            step=1,
            order=1,
            required=False,
            is_active=True,
            quote_relevant=True,
            quote_mapping_key='entry_date',
            quote_value_type='date',
        )

    def _submission(self, entry_date_text='2026-06-10', code='svc_hist'):
        return SurveySubmission.objects.create(
            user=self.user,
            email=self.user.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={
                'entry_date_hist': entry_date_text,
                'service_delivery_mode': 'per_service',
                'service_delivery_per_service': {code: 'agent_direct'},
            },
            requested_required_services=[code],
            requested_optional_services=[],
        )

    def test_deterministic_fallback_behavior(self):
        sub = self._submission(code='svc_det')
        ctx = build_scheduling_context(sub)

        first = recommend_schedule_placements(ctx, submission=sub)
        second = recommend_schedule_placements(ctx, submission=sub)

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(first[0]['code'], second[0]['code'])
        self.assertEqual(first[0]['starts_at'], second[0]['starts_at'])
        self.assertEqual(first[0]['ends_at'], second[0]['ends_at'])
        self.assertEqual(first[0]['recommendation_source'], second[0]['recommendation_source'])

    def test_recommendation_metadata_population(self):
        # create delivered historical items (SENT/ACTIVE) for the same service code
        hist_submission = self._submission(entry_date_text='2026-04-01', code='svc_meta')
        hist_plan = ServiceSchedulePlan.objects.create(
            submission=hist_submission,
            customer=self.user,
            status=ServiceSchedulePlan.Status.SENT,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=1,
        )
        start_dt = timezone.make_aware(timezone.datetime(2026, 4, 4, 11, 0, 0))
        ServiceScheduleItem.objects.create(
            schedule_plan=hist_plan,
            service_code='svc_meta',
            service_label='Meta Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=start_dt,
            ends_at=start_dt + timedelta(hours=1),
            duration_minutes=60,
            status=ServiceScheduleItem.ItemStatus.CONFIRMED,
        )
        user_hist2 = User.objects.create_user(
            username='hist_customer_meta2',
            email='hist_customer_meta2@test.com',
            password='testpass123',
        )
        hist_submission2 = SurveySubmission.objects.create(
            user=user_hist2,
            email=user_hist2.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={
                'entry_date_hist': '2026-04-03',
                'service_delivery_mode': 'per_service',
                'service_delivery_per_service': {'svc_meta': 'agent_direct'},
            },
            requested_required_services=['svc_meta'],
            requested_optional_services=[],
        )
        hist_plan2 = ServiceSchedulePlan.objects.create(
            submission=hist_submission2,
            customer=self.user,
            status=ServiceSchedulePlan.Status.ACTIVE,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=2,
        )
        start_dt2 = timezone.make_aware(timezone.datetime(2026, 4, 7, 10, 0, 0))
        ServiceScheduleItem.objects.create(
            schedule_plan=hist_plan2,
            service_code='svc_meta',
            service_label='Meta Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=start_dt2,
            ends_at=start_dt2 + timedelta(hours=1),
            duration_minutes=60,
            status=ServiceScheduleItem.ItemStatus.CONFIRMED,
        )

        user2 = User.objects.create_user(
            username='hist_customer2',
            email='hist_customer2@test.com',
            password='testpass123',
        )
        target_submission = SurveySubmission.objects.create(
            user=user2,
            email=user2.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={
                'entry_date_hist': '2026-06-10',
                'service_delivery_mode': 'per_service',
                'service_delivery_per_service': {'svc_meta': 'agent_direct'},
            },
            requested_required_services=['svc_meta'],
            requested_optional_services=[],
        )
        plan = generate_schedule_draft(target_submission, service_type_whitelist={ServiceScheduleItem.ServiceType.IN_PERSON_AGENT})
        item = plan.items.first()

        self.assertIsNotNone(item)
        self.assertIsNotNone(item.source_score)
        self.assertTrue((item.source_reason or '').strip())
        self.assertIn(item.recommendation_source, ('historical', 'rule_based', 'fallback'))
        self.assertIn('evidence=', item.source_reason)
        self.assertIn('samples=', item.source_reason)
        self.assertIn(item.needs_admin_review, (True, False))

    def test_strong_historical_match_case(self):
        hist_submission = self._submission(entry_date_text='2026-05-01', code='svc_strong')
        hist_plan = ServiceSchedulePlan.objects.create(
            submission=hist_submission,
            customer=self.user,
            status=ServiceSchedulePlan.Status.SENT,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=1,
        )
        s1 = timezone.make_aware(timezone.datetime(2026, 5, 4, 10, 0, 0))
        ServiceScheduleItem.objects.create(
            schedule_plan=hist_plan,
            service_code='svc_strong',
            service_label='Strong Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=s1,
            ends_at=s1 + timedelta(hours=1),
            duration_minutes=60,
            status=ServiceScheduleItem.ItemStatus.CONFIRMED,
        )

        user_hist2 = User.objects.create_user(
            username='hist_customer_strong2',
            email='hist_customer_strong2@test.com',
            password='testpass123',
        )
        hist_submission2 = SurveySubmission.objects.create(
            user=user_hist2,
            email=user_hist2.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={
                'entry_date_hist': '2026-05-02',
                'service_delivery_mode': 'per_service',
                'service_delivery_per_service': {'svc_strong': 'agent_direct'},
            },
            requested_required_services=['svc_strong'],
            requested_optional_services=[],
        )
        hist_plan2 = ServiceSchedulePlan.objects.create(
            submission=hist_submission2,
            customer=self.user,
            status=ServiceSchedulePlan.Status.ACTIVE,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=2,
        )
        s2 = timezone.make_aware(timezone.datetime(2026, 5, 6, 11, 0, 0))
        ServiceScheduleItem.objects.create(
            schedule_plan=hist_plan2,
            service_code='svc_strong',
            service_label='Strong Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=s2,
            ends_at=s2 + timedelta(hours=1),
            duration_minutes=60,
            status=ServiceScheduleItem.ItemStatus.CONFIRMED,
        )

        target_user = User.objects.create_user(
            username='hist_customer_target_strong',
            email='hist_customer_target_strong@test.com',
            password='testpass123',
        )
        target = SurveySubmission.objects.create(
            user=target_user,
            email=target_user.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={
                'entry_date_hist': '2026-06-10',
                'service_delivery_mode': 'per_service',
                'service_delivery_per_service': {'svc_strong': 'agent_direct'},
            },
            requested_required_services=['svc_strong'],
            requested_optional_services=[],
        )
        plan = generate_schedule_draft(target, service_type_whitelist={ServiceScheduleItem.ServiceType.IN_PERSON_AGENT})
        item = plan.items.first()

        self.assertIsNotNone(item)
        self.assertEqual(item.recommendation_source, 'historical')
        self.assertIn('evidence=historical-match', item.source_reason)

    def test_weak_historical_match_uses_statistical_prior(self):
        other = User.objects.create_user(
            username='hist_other',
            email='hist_other@test.com',
            password='testpass123',
        )
        h1 = SurveySubmission.objects.create(
            user=other,
            email=other.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={
                'entry_date_hist': '2026-03-01',
                'service_delivery_mode': 'per_service',
                'service_delivery_per_service': {'svc_weak': 'agent_direct', 'svc_other': 'agent_direct'},
            },
            requested_required_services=['svc_weak', 'svc_other'],
            requested_optional_services=[],
        )
        p1 = ServiceSchedulePlan.objects.create(
            submission=h1,
            customer=other,
            status=ServiceSchedulePlan.Status.SENT,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=1,
        )
        t1 = timezone.make_aware(timezone.datetime(2026, 3, 8, 9, 0, 0))
        ServiceScheduleItem.objects.create(
            schedule_plan=p1,
            service_code='svc_weak',
            service_label='Weak Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=t1,
            ends_at=t1 + timedelta(hours=1),
            duration_minutes=60,
            status=ServiceScheduleItem.ItemStatus.CONFIRMED,
        )

        other2 = User.objects.create_user(
            username='hist_other_2',
            email='hist_other_2@test.com',
            password='testpass123',
        )
        h2 = SurveySubmission.objects.create(
            user=other2,
            email=other2.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={
                'entry_date_hist': '2026-03-02',
                'service_delivery_mode': 'per_service',
                'service_delivery_per_service': {'svc_weak': 'agent_direct', 'svc_other': 'agent_direct'},
            },
            requested_required_services=['svc_weak', 'svc_other'],
            requested_optional_services=[],
        )
        p2 = ServiceSchedulePlan.objects.create(
            submission=h2,
            customer=other,
            status=ServiceSchedulePlan.Status.ACTIVE,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=2,
        )
        t2 = timezone.make_aware(timezone.datetime(2026, 3, 10, 9, 0, 0))
        ServiceScheduleItem.objects.create(
            schedule_plan=p2,
            service_code='svc_weak',
            service_label='Weak Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=t2,
            ends_at=t2 + timedelta(hours=1),
            duration_minutes=60,
            status=ServiceScheduleItem.ItemStatus.CONFIRMED,
        )

        target = self._submission(entry_date_text='2026-10-10', code='svc_weak')
        plan = generate_schedule_draft(target, service_type_whitelist={ServiceScheduleItem.ServiceType.IN_PERSON_AGENT})
        item = plan.items.first()

        self.assertIsNotNone(item)
        self.assertIn('evidence=statistical-prior', item.source_reason)

    def test_missing_history_fallback(self):
        sub = self._submission(code='svc_no_history')
        ctx = build_scheduling_context(sub)

        placements = recommend_schedule_placements(ctx, submission=sub)

        self.assertEqual(len(placements), 1)
        self.assertEqual(placements[0]['recommendation_source'], 'fallback')

    def test_no_past_date_recommendations(self):
        sub = self._submission(entry_date_text='2020-01-01', code='svc_old')
        ctx = build_scheduling_context(sub)

        placements = recommend_schedule_placements(ctx, submission=sub)

        self.assertEqual(len(placements), 1)
        self.assertGreaterEqual(placements[0]['starts_at'].date(), timezone.now().date())
