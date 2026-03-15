from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from settlement.models import ServiceScheduleItem, ServiceSchedulePlan
from survey.models import SurveySubmission


User = get_user_model()


class CaseStageScheduleAdminTransitionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='case_stage_admin',
            email='case_stage_admin@test.com',
            password='adminpass123',
            role=User.Role.ADMIN,
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='case_stage_customer',
            email='case_stage_customer@test.com',
            password='custpass123',
            role=User.Role.CUSTOMER,
        )
        self.agent = User.objects.create_user(
            username='case_stage_agent',
            email='case_stage_agent@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
            agent_states=['NC'],
        )

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.AGENT_ASSIGNMENT,
            case_stage=SurveySubmission.CaseStage.PAYMENT_COMPLETED,
            requested_required_services=['svc_case_stage'],
            answers={
                'region': 'North Carolina',
                'service_delivery_per_service': {'svc_case_stage': 'agent_direct'},
            },
        )
        self.plan = ServiceSchedulePlan.objects.create(
            submission=self.submission,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.REVIEWING,
            source=ServiceSchedulePlan.Source.ADMIN,
            version=1,
            created_by=self.admin,
            updated_by=self.admin,
        )
        start_at = timezone.now() + timedelta(days=1)
        ServiceScheduleItem.objects.create(
            schedule_plan=self.plan,
            service_code='svc_case_stage',
            service_label='Case Stage Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=start_at,
            ends_at=start_at + timedelta(hours=1),
            duration_minutes=60,
            assigned_agent=self.agent,
            status=ServiceScheduleItem.ItemStatus.SCHEDULED,
        )

    def test_request_availability_advances_case_stage(self):
        self.client.force_login(self.admin)
        url = reverse('app_submission_review_schedule_request_availability', kwargs={'submission_id': self.submission.id})

        with patch('config.schedule_admin_views.get_agents_needing_availability', return_value=[self.agent.id]), \
             patch('config.schedule_admin_views.send_availability_request_to_agent', return_value=True):
            response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.case_stage, SurveySubmission.CaseStage.AVAILABILITY_REQUESTED)

    def test_send_lsa_advances_case_stage(self):
        self.client.force_login(self.admin)
        url = reverse('app_submission_review_schedule_send_lsa', kwargs={'submission_id': self.submission.id})

        class _Batch:
            id = 99
            schedule_plan_id = 1
            schedule_version = 1

        with patch('config.schedule_admin_views.send_lsa_batch_for_schedule_plan', return_value=(_Batch(), [object()])):
            response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.case_stage, SurveySubmission.CaseStage.LSA_PENDING)

    def test_finalize_schedule_advances_case_stage(self):
        self.client.force_login(self.admin)
        self.submission.advance_case_stage(SurveySubmission.CaseStage.LSA_PENDING)
        url = reverse('app_submission_review_schedule_finalize', kwargs={'submission_id': self.submission.id})

        with patch('settlement.notifications.send_schedule_sent_to_customer', return_value=True):
            response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 200)
        self.submission.refresh_from_db()
        self.plan.refresh_from_db()
        self.assertEqual(self.submission.case_stage, SurveySubmission.CaseStage.SCHEDULE_FINALIZED)
        self.assertEqual(self.plan.status, ServiceSchedulePlan.Status.SENT)
