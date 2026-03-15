from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from settlement.models import ServiceScheduleItem, ServiceSchedulePlan, UserSettlementPlan
from survey.models import SurveySubmission


User = get_user_model()


class CustomerDashboardCalendarVisibilityTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_dash_cal',
            email='admin_dash_cal@test.com',
            password='adminpass123',
            role=User.Role.ADMIN,
        )
        self.customer = User.objects.create_user(
            username='customer_dash_cal',
            email='customer_dash_cal@test.com',
            password='custpass123',
            role=User.Role.CUSTOMER,
        )
        self.url = reverse('app_customer_dashboard')

    def test_calendar_hidden_while_submission_is_still_under_admin_review(self):
        SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={},
        )
        UserSettlementPlan.objects.create(
            user=self.customer,
            state='North Carolina',
            city='Morrisville',
            entry_date=timezone.now().date(),
            service_schedule={
                timezone.now().date().isoformat(): [
                    {'code': 'airport_pickup', 'label': '공항픽업'},
                ]
            },
        )

        self.client.force_login(self.customer)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['show_customer_calendar'])
        self.assertContains(response, 'When the admin finalizes the schedule, the calendar appears.')

    def test_calendar_shows_after_schedule_is_released(self):
        submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={},
        )
        UserSettlementPlan.objects.create(
            user=self.customer,
            state='North Carolina',
            city='Morrisville',
            entry_date=timezone.now().date(),
            service_schedule={},
        )
        plan = ServiceSchedulePlan.objects.create(
            submission=submission,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.SENT,
            source=ServiceSchedulePlan.Source.ADMIN,
            version=1,
            created_by=self.admin,
            updated_by=self.admin,
        )
        start = timezone.now() + timedelta(days=1)
        ServiceScheduleItem.objects.create(
            schedule_plan=plan,
            service_code='airport_pickup',
            service_label='공항픽업',
            service_type=ServiceScheduleItem.ServiceType.AI_AGENT,
            starts_at=start,
            ends_at=start + timedelta(hours=1),
            duration_minutes=60,
            status=ServiceScheduleItem.ItemStatus.SCHEDULED,
        )

        self.client.force_login(self.customer)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['show_customer_calendar'])
        self.assertContains(response, 'My Relocation Plan')
        self.assertContains(response, 'airport pickup')

    def test_calendar_hidden_for_agent_assignment_when_only_legacy_schedule_exists(self):
        SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.AGENT_ASSIGNMENT,
            answers={},
        )
        UserSettlementPlan.objects.create(
            user=self.customer,
            state='North Carolina',
            city='Morrisville',
            entry_date=timezone.now().date(),
            service_schedule={
                timezone.now().date().isoformat(): [
                    {'code': 'ssn_service', 'label': 'SSN 신청 : 소셜국 동행/통역'},
                ]
            },
        )

        self.client.force_login(self.customer)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['show_customer_calendar'])
        self.assertNotContains(response, 'My Relocation Plan')
        self.assertContains(response, 'When the admin finalizes the schedule, the calendar appears.')
