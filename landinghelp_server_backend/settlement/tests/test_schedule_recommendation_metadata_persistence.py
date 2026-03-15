from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from settlement.models import ServiceScheduleItem, ServiceSchedulePlan
from settlement.scheduling_engine import generate_schedule_draft
from settlement.schedule_utils import serialize_schedule_items_for_calendar
from survey.models import SurveyQuestion, SurveySubmission


User = get_user_model()


class ScheduleRecommendationMetadataPersistenceTests(TestCase):
    def setUp(self):
        SurveyQuestion.objects.create(
            key='entry_date_meta_persist',
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

    def _submission(self, username, email, code='svc_meta_persist', entry_date='2026-07-10'):
        user = User.objects.create_user(username=username, email=email, password='testpass123')
        return SurveySubmission.objects.create(
            user=user,
            email=user.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={
                'entry_date_meta_persist': entry_date,
                'service_delivery_mode': 'per_service',
                'service_delivery_per_service': {code: 'agent_direct'},
            },
            requested_required_services=[code],
            requested_optional_services=[],
        )

    def test_metadata_persistence(self):
        sub = self._submission('meta_persist_user', 'meta_persist_user@test.com')
        plan = generate_schedule_draft(
            sub,
            service_type_whitelist={ServiceScheduleItem.ServiceType.IN_PERSON_AGENT},
        )
        item = plan.items.first()

        self.assertIsNotNone(item)
        self.assertIsInstance(item.recommendation_metadata, dict)
        self.assertIn('confidence_score', item.recommendation_metadata)
        self.assertIn('recommendation_reason', item.recommendation_metadata)
        self.assertIn('evidence_type', item.recommendation_metadata)
        self.assertIn('similar_historical_sample_count', item.recommendation_metadata)
        self.assertIn('suggested_day_offset_from_entry', item.recommendation_metadata)
        self.assertIn('needs_admin_review', item.recommendation_metadata)

    def test_old_records_remain_readable(self):
        customer = User.objects.create_user(
            username='meta_old_customer',
            email='meta_old_customer@test.com',
            password='testpass123',
        )
        sub = SurveySubmission.objects.create(
            user=customer,
            email=customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={},
            requested_required_services=['svc_old_meta'],
            requested_optional_services=[],
        )
        plan = ServiceSchedulePlan.objects.create(
            submission=sub,
            customer=customer,
            status=ServiceSchedulePlan.Status.DRAFT,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=1,
        )
        start_dt = timezone.now() + timedelta(days=1)
        item = ServiceScheduleItem.objects.create(
            schedule_plan=plan,
            service_code='svc_old_meta',
            service_label='Old Meta Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=start_dt,
            ends_at=start_dt + timedelta(hours=1),
            duration_minutes=60,
            status=ServiceScheduleItem.ItemStatus.SCHEDULED,
            source_score=82.5,
            source_reason='legacy reason only',
            recommendation_source='historical',
            needs_admin_review=False,
            recommendation_metadata={},
        )

        serialized = serialize_schedule_items_for_calendar(plan)
        self.assertEqual(len(serialized), 1)
        row = serialized[0]
        self.assertEqual(row['id'], item.id)
        self.assertEqual(row['recommendation_reason'], 'legacy reason only')
        self.assertEqual(row['recommendation_source'], 'historical')
        self.assertEqual(row['recommendation_metadata'], {})

    def test_new_drafts_contain_recommendation_evidence(self):
        hist_sub = self._submission('meta_hist_user', 'meta_hist_user@test.com', code='svc_new_meta', entry_date='2026-05-10')
        hist_plan = ServiceSchedulePlan.objects.create(
            submission=hist_sub,
            customer=hist_sub.user,
            status=ServiceSchedulePlan.Status.SENT,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=1,
        )
        hist_start = timezone.make_aware(timezone.datetime(2026, 5, 13, 10, 0, 0))
        ServiceScheduleItem.objects.create(
            schedule_plan=hist_plan,
            service_code='svc_new_meta',
            service_label='Meta Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=hist_start,
            ends_at=hist_start + timedelta(hours=1),
            duration_minutes=60,
            status=ServiceScheduleItem.ItemStatus.CONFIRMED,
        )

        target_sub = self._submission('meta_target_user', 'meta_target_user@test.com', code='svc_new_meta', entry_date='2026-06-10')
        target_plan = generate_schedule_draft(
            target_sub,
            service_type_whitelist={ServiceScheduleItem.ServiceType.IN_PERSON_AGENT},
        )
        item = target_plan.items.first()

        self.assertIsNotNone(item)
        metadata = item.recommendation_metadata
        self.assertIsInstance(metadata, dict)
        self.assertIn(metadata.get('evidence_type'), ('historical-match', 'statistical-prior', 'rule-based-fallback'))
        self.assertIsNotNone(metadata.get('confidence_score'))
        self.assertIn('remaining_days_band', metadata)
