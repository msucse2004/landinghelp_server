from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from settlement.models import ServiceScheduleItem, ServiceSchedulePlan
from settlement.schedule_training_data import get_training_eligible_historical_examples
from survey.models import SurveyQuestion, SurveySubmission


User = get_user_model()


class ScheduleTrainingDataDefinitionTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='training_customer',
            email='training_customer@test.com',
            password='testpass123',
        )
        SurveyQuestion.objects.create(
            key='entry_date_training',
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

    def _submission(self, entry_date='2026-08-10'):
        return SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={
                'entry_date_training': entry_date,
                'service_delivery_mode': 'per_service',
                'service_delivery_per_service': {'svc_training': 'agent_direct'},
            },
            requested_required_services=['svc_training'],
            requested_optional_services=[],
        )

    def _submission_for_user(self, user, entry_date='2026-08-10'):
        return SurveySubmission.objects.create(
            user=user,
            email=user.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={
                'entry_date_training': entry_date,
                'service_delivery_mode': 'per_service',
                'service_delivery_per_service': {'svc_training': 'agent_direct'},
            },
            requested_required_services=['svc_training'],
            requested_optional_services=[],
        )

    def _plan_with_item(self, submission, status, *, complete=True, service_code='svc_training'):
        plan = ServiceSchedulePlan.objects.create(
            submission=submission,
            customer=self.customer,
            status=status,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=1,
        )
        start = timezone.now() + timedelta(days=3)
        end = start + timedelta(hours=1)
        if not complete:
            end = None

        ServiceScheduleItem.objects.create(
            schedule_plan=plan,
            service_code=service_code,
            service_label='Training Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=start,
            ends_at=end,
            duration_minutes=60,
            status=ServiceScheduleItem.ItemStatus.CONFIRMED,
        )
        return plan

    def test_sent_active_included_and_finalized_excluded(self):
        sub = self._submission()
        plan_finalized = self._plan_with_item(sub, ServiceSchedulePlan.Status.FINALIZED)
        plan_sent = self._plan_with_item(sub, ServiceSchedulePlan.Status.SENT, service_code='svc_training_sent')
        plan_active = self._plan_with_item(sub, ServiceSchedulePlan.Status.ACTIVE, service_code='svc_training_active')

        examples = get_training_eligible_historical_examples(max_items=200)
        plan_ids = {row['plan_id'] for row in examples}

        self.assertIn(plan_sent.id, plan_ids)
        self.assertIn(plan_active.id, plan_ids)
        self.assertNotIn(plan_finalized.id, plan_ids)

    def test_draft_and_reviewing_excluded(self):
        sub = self._submission()
        plan_draft = self._plan_with_item(sub, ServiceSchedulePlan.Status.DRAFT, service_code='svc_training_draft')
        plan_reviewing = self._plan_with_item(sub, ServiceSchedulePlan.Status.REVIEWING, service_code='svc_training_reviewing')
        plan_sent = self._plan_with_item(sub, ServiceSchedulePlan.Status.SENT, service_code='svc_training_ok')

        examples = get_training_eligible_historical_examples(max_items=200)
        plan_ids = {row['plan_id'] for row in examples}

        self.assertNotIn(plan_draft.id, plan_ids)
        self.assertNotIn(plan_reviewing.id, plan_ids)
        self.assertIn(plan_sent.id, plan_ids)

    def test_incomplete_or_missing_context_excluded(self):
        good_sub = self._submission(entry_date='2026-08-10')
        customer2 = User.objects.create_user(
            username='training_customer2',
            email='training_customer2@test.com',
            password='testpass123',
        )
        missing_entry_sub = self._submission_for_user(customer2, entry_date='')

        good_plan = self._plan_with_item(good_sub, ServiceSchedulePlan.Status.SENT, service_code='svc_training_good')
        incomplete_plan = self._plan_with_item(good_sub, ServiceSchedulePlan.Status.SENT, complete=False, service_code='svc_training_incomplete')
        missing_context_plan = self._plan_with_item(missing_entry_sub, ServiceSchedulePlan.Status.SENT, service_code='svc_training_missing_ctx')

        examples = get_training_eligible_historical_examples(max_items=200)
        plan_ids = {row['plan_id'] for row in examples}

        self.assertIn(good_plan.id, plan_ids)
        self.assertNotIn(incomplete_plan.id, plan_ids)
        self.assertNotIn(missing_context_plan.id, plan_ids)
