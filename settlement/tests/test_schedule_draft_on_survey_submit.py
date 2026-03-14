from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from settlement.models import ServiceScheduleItem, ServiceSchedulePlan
from survey.models import SurveyQuestion, SurveySubmission


User = get_user_model()


class SurveySubmitScheduleDraftTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='draft_customer',
            email='draft_customer@test.com',
            password='testpass123',
        )
        SurveyQuestion.objects.create(
            key='entry_date_for_schedule_draft',
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

    def _submit(self):
        self.client.force_login(self.user)
        return self.client.post(reverse('survey:survey_submit'))

    def _build_submission(self, *, status, entry_date_value='2026-04-10'):
        return SurveySubmission.objects.create(
            user=self.user,
            email=self.user.email,
            status=status,
            answers={
                'entry_date_for_schedule_draft': entry_date_value,
                'service_delivery_mode': 'per_service',
                'service_delivery_per_service': {
                    'svc_in_person': 'agent_direct',
                    'svc_ai': 'ai_service',
                    'svc_self': 'self_search',
                },
            },
            requested_required_services=['svc_in_person', 'svc_ai', 'svc_self'],
            requested_optional_services=[],
        )

    def test_survey_completion_creates_schedule_draft(self):
        submission = self._build_submission(status=SurveySubmission.Status.DRAFT)

        response = self._submit()
        self.assertEqual(response.status_code, 302)

        plans = ServiceSchedulePlan.objects.filter(
            submission=submission,
            status=ServiceSchedulePlan.Status.DRAFT,
        )
        self.assertEqual(plans.count(), 1)

    def test_repeated_completion_does_not_duplicate_active_draft(self):
        submission = self._build_submission(status=SurveySubmission.Status.REVISION_REQUESTED)

        existing_plan = ServiceSchedulePlan.objects.create(
            submission=submission,
            customer=self.user,
            status=ServiceSchedulePlan.Status.DRAFT,
            source=ServiceSchedulePlan.Source.ADMIN,
            version=1,
        )
        ServiceScheduleItem.objects.create(
            schedule_plan=existing_plan,
            service_code='svc_in_person',
            service_label='In Person Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=timezone.now() + timedelta(days=1),
            ends_at=timezone.now() + timedelta(days=1, hours=1),
            duration_minutes=60,
            status=ServiceScheduleItem.ItemStatus.SCHEDULED,
        )

        response = self._submit()
        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            ServiceSchedulePlan.objects.filter(
                submission=submission,
                status__in=(ServiceSchedulePlan.Status.DRAFT, ServiceSchedulePlan.Status.REVIEWING),
            ).count(),
            1,
        )

    def test_only_schedulable_in_person_services_are_included(self):
        submission = self._build_submission(status=SurveySubmission.Status.DRAFT)

        response = self._submit()
        self.assertEqual(response.status_code, 302)

        plan = ServiceSchedulePlan.objects.filter(submission=submission).order_by('-updated_at').first()
        self.assertIsNotNone(plan)
        items = list(plan.items.all())
        self.assertTrue(items)

        self.assertEqual({it.service_code for it in items}, {'svc_in_person'})
        self.assertEqual(
            {it.service_type for it in items},
            {ServiceScheduleItem.ServiceType.IN_PERSON_AGENT},
        )

    def test_invalid_or_missing_entry_date_is_handled_safely(self):
        invalid_submission = self._build_submission(
            status=SurveySubmission.Status.DRAFT,
            entry_date_value='not-a-date',
        )

        response = self._submit()
        self.assertEqual(response.status_code, 302)

        invalid_plan = ServiceSchedulePlan.objects.filter(submission=invalid_submission).first()
        self.assertIsNotNone(invalid_plan)
        invalid_item = invalid_plan.items.first()
        self.assertIsNotNone(invalid_item)
        self.assertIsNotNone(invalid_item.starts_at)

        user2 = User.objects.create_user(
            username='draft_customer2',
            email='draft_customer2@test.com',
            password='testpass123',
        )
        missing_submission = SurveySubmission.objects.create(
            user=user2,
            email=user2.email,
            status=SurveySubmission.Status.DRAFT,
            answers={
                'service_delivery_mode': 'bulk',
                'service_delivery_preference': 'agent_direct',
            },
            requested_required_services=['svc_in_person_only'],
            requested_optional_services=[],
        )

        self.client.force_login(user2)
        response2 = self.client.post(reverse('survey:survey_submit'))
        self.assertEqual(response2.status_code, 302)

        missing_plan = ServiceSchedulePlan.objects.filter(submission=missing_submission).first()
        self.assertIsNotNone(missing_plan)
        missing_item = missing_plan.items.first()
        self.assertIsNotNone(missing_item)
        self.assertIsNotNone(missing_item.starts_at)
