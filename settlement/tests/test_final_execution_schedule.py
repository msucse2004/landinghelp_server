from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from settlement.schedule_utils import get_schedule_for_display
from settlement.models import (
    LsaAgentContract,
    LsaAgentRequest,
    LsaAgentResponse,
    LsaAgentResponseItem,
    LsaSourcingBatch,
    ServiceScheduleItem,
    ServiceSchedulePlan,
)
from survey.models import SurveySubmission


User = get_user_model()


class FinalExecutionScheduleTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_exec',
            email='admin_exec@test.com',
            password='adminpass123',
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='customer_exec',
            email='customer_exec@test.com',
            password='custpass123',
        )
        self.agent = User.objects.create_user(
            username='agent_exec',
            email='agent_exec@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={},
            requested_required_services=['svc_exec'],
        )
        self.admin_plan = ServiceSchedulePlan.objects.create(
            submission=self.submission,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.FINALIZED,
            source=ServiceSchedulePlan.Source.ADMIN,
            version=4,
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.base_start = timezone.now() + timedelta(days=5)
        self.base_end = self.base_start + timedelta(hours=1)
        self.base_item = ServiceScheduleItem.objects.create(
            schedule_plan=self.admin_plan,
            service_code='svc_exec',
            service_label='Execution Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=self.base_start,
            ends_at=self.base_end,
            duration_minutes=60,
            status=ServiceScheduleItem.ItemStatus.SCHEDULED,
            source_reason='internal negotiation reason',
            recommendation_source='historical',
            needs_admin_review=True,
            notes='internal note to admin',
        )

        self.batch = LsaSourcingBatch.objects.create(
            submission=self.submission,
            schedule_plan=self.admin_plan,
            schedule_version=self.admin_plan.version,
            proposed_schedule_snapshot=[{
                'service_code': 'svc_exec',
                'service_label': 'Execution Service',
                'starts_at': self.base_start.isoformat(),
                'ends_at': self.base_end.isoformat(),
            }],
            requested_services_snapshot=[{'code': 'svc_exec', 'label': 'Execution Service'}],
            internal_pricing_snapshot=[{'service_code': 'svc_exec', 'internal_agent_price': 200.0, 'currency': 'USD'}],
            created_by=self.admin,
        )
        self.req = LsaAgentRequest.objects.create(
            batch=self.batch,
            target_agent=self.agent,
            status=LsaAgentRequest.Status.RESPONDED,
            payload_snapshot={'proposed_schedule': self.batch.proposed_schedule_snapshot},
            responded_at=timezone.now(),
        )
        self.response = LsaAgentResponse.objects.create(
            request=self.req,
            responded_by=self.agent,
            decision=LsaAgentResponse.Decision.PARTIAL,
            note='can move +1 day',
            revision=1,
        )
        self.suggested_start = self.base_start + timedelta(days=1)
        self.suggested_end = self.base_end + timedelta(days=1)
        LsaAgentResponseItem.objects.create(
            response=self.response,
            service_code='svc_exec',
            service_label='Execution Service',
            proposed_starts_at=self.base_start,
            proposed_ends_at=self.base_end,
            action=LsaAgentResponseItem.Action.SUGGEST_CHANGE,
            suggested_starts_at=self.suggested_start,
            suggested_ends_at=self.suggested_end,
            note='agent suggestion internal',
        )

    def _select_url(self):
        return reverse('app_submission_review_lsa_select_agent', kwargs={'submission_id': self.submission.id, 'batch_id': self.batch.id})

    def _select_agent(self):
        self.client.force_login(self.admin)
        return self.client.post(
            self._select_url(),
            data={
                'request_id': self.req.id,
                'response_id': self.response.id,
                'note': 'approve suggestion',
            },
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

    def test_final_schedule_generated_correctly(self):
        res = self._select_agent()
        self.assertEqual(res.status_code, 200)

        contract = LsaAgentContract.objects.get(batch=self.batch)
        self.assertIsNotNone(contract.execution_schedule_plan_id)
        final_plan = contract.execution_schedule_plan
        self.assertEqual(final_plan.status, ServiceSchedulePlan.Status.ACTIVE)
        self.assertEqual(final_plan.based_on_id, self.admin_plan.id)

        final_item = final_plan.items.get(service_code='svc_exec')
        self.assertEqual(final_item.assigned_agent_id, self.agent.id)
        self.assertEqual(final_item.starts_at, self.suggested_start)
        self.assertEqual(final_item.ends_at, self.suggested_end)
        self.assertEqual(final_item.recommendation_source, 'agent_finalized')

    def test_draft_history_preserved(self):
        before_start = self.base_item.starts_at
        before_end = self.base_item.ends_at
        before_notes = self.base_item.notes

        res = self._select_agent()
        self.assertEqual(res.status_code, 200)

        self.base_item.refresh_from_db()
        self.assertEqual(self.base_item.starts_at, before_start)
        self.assertEqual(self.base_item.ends_at, before_end)
        self.assertEqual(self.base_item.notes, before_notes)
        self.assertEqual(self.admin_plan.status, ServiceSchedulePlan.Status.FINALIZED)

    def test_customer_cannot_see_internal_negotiation_metadata(self):
        res = self._select_agent()
        self.assertEqual(res.status_code, 200)

        schedule = get_schedule_for_display(self.customer)
        self.assertTrue(schedule)
        first_day = next(iter(schedule.keys()))
        first_item = schedule[first_day][0]

        self.assertNotIn('notes', first_item)
        self.assertNotIn('location_text', first_item)
        self.assertNotIn('agent_id', first_item)
        self.assertNotIn('source_reason', first_item)
        self.assertNotIn('recommendation_reason', first_item)
