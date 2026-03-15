from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from settlement.models import ServiceScheduleItem, ServiceSchedulePlan
from survey.models import SurveySubmission


User = get_user_model()


class ScheduleFinalizePermissionTests(TestCase):
    def setUp(self):
        self.super_admin = User.objects.create_user(
            username='sched_perm_super_admin',
            email='sched_perm_super_admin@test.com',
            password='pass1234',
            role=User.Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.admin = User.objects.create_user(
            username='sched_perm_admin',
            email='sched_perm_admin@test.com',
            password='pass1234',
            role=User.Role.ADMIN,
            is_staff=True,
        )
        self.supervisor = User.objects.create_user(
            username='sched_perm_supervisor',
            email='sched_perm_supervisor@test.com',
            password='pass1234',
            role=User.Role.SUPERVISOR,
            is_staff=True,
        )
        self.hq_staff = User.objects.create_user(
            username='sched_perm_hq',
            email='sched_perm_hq@test.com',
            password='pass1234',
            role=User.Role.HQ_STAFF,
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='sched_perm_customer',
            email='sched_perm_customer@test.com',
            password='pass1234',
            role=User.Role.CUSTOMER,
        )
        self.agent = User.objects.create_user(
            username='sched_perm_agent',
            email='sched_perm_agent@test.com',
            password='pass1234',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
            agent_states=['NC'],
        )

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.AGENT_ASSIGNMENT,
            case_stage=SurveySubmission.CaseStage.PAYMENT_COMPLETED,
            requested_required_services=['svc_perm'],
            answers={
                'region': 'North Carolina',
                'service_delivery_per_service': {'svc_perm': 'agent_direct'},
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
        self.item = ServiceScheduleItem.objects.create(
            schedule_plan=self.plan,
            service_code='svc_perm',
            service_label='Permission Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=start_at,
            ends_at=start_at + timedelta(hours=1),
            duration_minutes=60,
            assigned_agent=self.agent,
            status=ServiceScheduleItem.ItemStatus.SCHEDULED,
        )

    def test_hq_staff_cannot_finalize_schedule(self):
        self.client.force_login(self.hq_staff)
        url = reverse('app_submission_review_schedule_finalize', kwargs={'submission_id': self.submission.id})
        response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 403)

    def test_customer_and_agent_cannot_finalize_schedule(self):
        url = reverse('app_submission_review_schedule_finalize', kwargs={'submission_id': self.submission.id})

        self.client.force_login(self.customer)
        customer_response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(customer_response.status_code, 302)

        self.client.force_login(self.agent)
        agent_response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(agent_response.status_code, 302)

    def test_supervisor_can_finalize_schedule(self):
        self.client.force_login(self.supervisor)
        self.submission.advance_case_stage(SurveySubmission.CaseStage.LSA_PENDING)
        url = reverse('app_submission_review_schedule_finalize', kwargs={'submission_id': self.submission.id})

        with patch('settlement.notifications.send_schedule_sent_to_customer', return_value=True):
            response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 200)
        self.submission.refresh_from_db()
        self.plan.refresh_from_db()
        self.assertEqual(self.submission.case_stage, SurveySubmission.CaseStage.SCHEDULE_FINALIZED)
        self.assertEqual(self.plan.status, ServiceSchedulePlan.Status.SENT)

    def test_hq_staff_cannot_optimize_schedule_items(self):
        self.client.force_login(self.hq_staff)
        url = reverse('app_submission_review_schedule_api', kwargs={'submission_id': self.submission.id})
        response = self.client.post(
            url,
            data={
                'items': [{
                    'id': self.item.id,
                    'service_code': self.item.service_code,
                    'service_label': self.item.service_label,
                    'starts_at': self.item.starts_at.isoformat(),
                    'ends_at': self.item.ends_at.isoformat(),
                    'duration_minutes': self.item.duration_minutes,
                    'assigned_agent_id': self.agent.id,
                    'status': self.item.status,
                }]
            },
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_send_lsa(self):
        self.client.force_login(self.admin)
        url = reverse('app_submission_review_schedule_send_lsa', kwargs={'submission_id': self.submission.id})

        class _Batch:
            id = 101
            schedule_plan_id = 1
            schedule_version = 1

        with patch(
            'config.schedule_admin_views._resolve_candidate_agents_for_submission',
            return_value=([self.agent], 'NC'),
        ), patch(
            'config.schedule_admin_views.send_lsa_batch_for_schedule_plan',
            return_value=(_Batch(), [object()]),
        ):
            response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 200)

    def test_hq_staff_cannot_send_lsa(self):
        self.client.force_login(self.hq_staff)
        url = reverse('app_submission_review_schedule_send_lsa', kwargs={'submission_id': self.submission.id})
        response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 403)
