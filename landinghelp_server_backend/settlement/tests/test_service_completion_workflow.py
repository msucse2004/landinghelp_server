import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from messaging.models import Conversation, Message
from settlement.models import ServiceCompletionForm, ServiceScheduleItem, ServiceSchedulePlan
from survey.models import SurveySubmission


User = get_user_model()


class ServiceCompletionWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='svc_completion_admin',
            email='svc_completion_admin@test.com',
            password='pass1234',
            role=User.Role.ADMIN,
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='svc_completion_customer',
            email='svc_completion_customer@test.com',
            password='pass1234',
            role=User.Role.CUSTOMER,
        )
        self.assigned_agent = User.objects.create_user(
            username='svc_completion_agent',
            email='svc_completion_agent@test.com',
            password='pass1234',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )
        self.other_agent = User.objects.create_user(
            username='svc_completion_agent_other',
            email='svc_completion_agent_other@test.com',
            password='pass1234',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SERVICE_IN_PROGRESS,
            case_stage=SurveySubmission.CaseStage.SERVICES_IN_PROGRESS,
            answers={},
        )
        self.plan = ServiceSchedulePlan.objects.create(
            submission=self.submission,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.ACTIVE,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=1,
            created_by=self.admin,
            updated_by=self.admin,
        )
        ended_start = timezone.now() - timedelta(hours=2)
        ServiceScheduleItem.objects.create(
            schedule_plan=self.plan,
            service_code='svc_done_1',
            service_label='Done Service 1',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=ended_start,
            ends_at=ended_start + timedelta(hours=1),
            duration_minutes=60,
            assigned_agent=self.assigned_agent,
            status=ServiceScheduleItem.ItemStatus.CONFIRMED,
        )

    def _submit_url(self):
        return reverse('api_settlement_service_completion_submit')

    def _list_url(self):
        return reverse('api_settlement_service_completion_forms')

    def test_assigned_agent_can_submit_after_all_assigned_services_completed(self):
        self.client.force_login(self.assigned_agent)
        response = self.client.post(
            self._submit_url(),
            data=json.dumps({
                'submission_id': self.submission.id,
                'schedule_plan_id': self.plan.id,
                'summary': 'All assigned services completed',
                'completion_notes': 'Delivered all in-person tasks',
                'attachments_count': 2,
            }),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)

        form = ServiceCompletionForm.objects.get(submission=self.submission, agent=self.assigned_agent, schedule_plan=self.plan)
        self.assertEqual(form.status, ServiceCompletionForm.Status.SUBMITTED)
        self.assertEqual(form.attachments_count, 2)

        local_conv = Conversation.objects.get(
            survey_submission=self.submission,
            workspace_type=Conversation.WorkspaceType.LOCAL_EXECUTION,
        )
        self.assertTrue(
            Message.objects.filter(conversation=local_conv, body__icontains='서비스 완료 보고서가 제출').exists()
        )

    def test_only_assigned_agent_can_submit(self):
        self.client.force_login(self.other_agent)
        response = self.client.post(
            self._submit_url(),
            data=json.dumps({
                'submission_id': self.submission.id,
                'schedule_plan_id': self.plan.id,
                'summary': 'I should be denied',
            }),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 403)

    def test_submit_denied_when_any_assigned_service_not_completed(self):
        future_start = timezone.now() + timedelta(hours=1)
        ServiceScheduleItem.objects.create(
            schedule_plan=self.plan,
            service_code='svc_not_done',
            service_label='Not Done Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=future_start,
            ends_at=future_start + timedelta(hours=1),
            duration_minutes=60,
            assigned_agent=self.assigned_agent,
            status=ServiceScheduleItem.ItemStatus.CONFIRMED,
        )

        self.client.force_login(self.assigned_agent)
        response = self.client.post(
            self._submit_url(),
            data=json.dumps({
                'submission_id': self.submission.id,
                'schedule_plan_id': self.plan.id,
                'summary': 'Too early',
            }),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 403)

    def test_internal_staff_can_review_but_agent_cannot(self):
        form = ServiceCompletionForm.objects.create(
            submission=self.submission,
            agent=self.assigned_agent,
            schedule_plan=self.plan,
            status=ServiceCompletionForm.Status.SUBMITTED,
            summary='Submitted summary',
            submitted_at=timezone.now(),
        )
        review_url = reverse('api_settlement_service_completion_review', kwargs={'form_id': form.id})

        self.client.force_login(self.assigned_agent)
        denied = self.client.post(review_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(denied.status_code, 403)

        self.client.force_login(self.admin)
        allowed = self.client.post(review_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(allowed.status_code, 200)

        form.refresh_from_db()
        self.assertEqual(form.status, ServiceCompletionForm.Status.REVIEWED)
        self.assertEqual(form.reviewed_by_id, self.admin.id)
        self.assertIsNotNone(form.reviewed_at)

    def test_visibility_agent_internal_and_customer_history(self):
        form = ServiceCompletionForm.objects.create(
            submission=self.submission,
            agent=self.assigned_agent,
            schedule_plan=self.plan,
            status=ServiceCompletionForm.Status.SUBMITTED,
            summary='Visibility summary',
            completion_notes='Internal notes',
            submitted_at=timezone.now(),
        )

        self.client.force_login(self.assigned_agent)
        agent_list = self.client.get(self._list_url(), {'submission_id': self.submission.id})
        self.assertEqual(agent_list.status_code, 200)
        self.assertEqual(len(agent_list.json().get('forms', [])), 1)

        self.client.force_login(self.admin)
        admin_list = self.client.get(self._list_url(), {'submission_id': self.submission.id})
        self.assertEqual(admin_list.status_code, 200)
        self.assertEqual(len(admin_list.json().get('forms', [])), 1)

        self.client.force_login(self.customer)
        customer_before_review = self.client.get(self._list_url(), {'submission_id': self.submission.id})
        self.assertEqual(customer_before_review.status_code, 200)
        self.assertEqual(customer_before_review.json().get('forms', []), [])

        form.status = ServiceCompletionForm.Status.REVIEWED
        form.reviewed_at = timezone.now()
        form.reviewed_by = self.admin
        form.save(update_fields=['status', 'reviewed_at', 'reviewed_by', 'updated_at'])

        customer_after_review = self.client.get(self._list_url(), {'submission_id': self.submission.id})
        self.assertEqual(customer_after_review.status_code, 200)
        forms = customer_after_review.json().get('forms', [])
        self.assertEqual(len(forms), 1)
        self.assertEqual(forms[0]['id'], form.id)
