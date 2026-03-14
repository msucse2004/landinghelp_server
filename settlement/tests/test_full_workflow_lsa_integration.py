from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from messaging.models import Conversation, ConversationParticipant, Message
from settlement.lsa_service import build_lsa_response_token
from settlement.models import (
    LsaAgentContract,
    LsaAgentRequest,
    ServiceSchedulePlan,
)
from settlement.schedule_utils import get_schedule_for_display
from survey.models import SurveyQuestion, SurveySubmission


User = get_user_model()


class FullWorkflowLsaIntegrationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_step11',
            email='admin_step11@test.com',
            password='adminpass123',
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='customer_step11',
            email='customer_step11@test.com',
            password='custpass123',
        )
        self.agent1 = User.objects.create_user(
            username='agent_step11_1',
            email='agent_step11_1@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
            agent_states=['NC'],
        )
        self.agent2 = User.objects.create_user(
            username='agent_step11_2',
            email='agent_step11_2@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
            agent_states=['NC'],
        )

        SurveyQuestion.objects.create(
            key='entry_date_step11',
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

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.DRAFT,
            answers={
                'entry_date_step11': '2026-04-20',
                'region': 'North Carolina',
                'service_delivery_mode': 'per_service',
                'service_delivery_per_service': {
                    'svc_step11_in_person': 'agent_direct',
                },
            },
            requested_required_services=['svc_step11_in_person'],
            requested_optional_services=[],
        )

    def test_end_to_end_workflow_from_survey_to_contract_and_role_aware_calendar(self):
        self.client.force_login(self.customer)
        submit_res = self.client.post(reverse('survey:survey_submit'))
        self.assertEqual(submit_res.status_code, 302)

        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, SurveySubmission.Status.SUBMITTED)

        draft_plan = ServiceSchedulePlan.objects.filter(
            submission=self.submission,
            status=ServiceSchedulePlan.Status.DRAFT,
        ).order_by('-updated_at').first()
        self.assertIsNotNone(draft_plan)

        self.client.force_login(self.admin)
        schedule_page = self.client.get(
            reverse('app_submission_review_schedule', kwargs={'submission_id': self.submission.id})
        )
        self.assertEqual(schedule_page.status_code, 200)

        schedule_api_url = reverse('app_submission_review_schedule_api', kwargs={'submission_id': self.submission.id})
        schedule_get = self.client.get(schedule_api_url, {'view': 'week'})
        self.assertEqual(schedule_get.status_code, 200)
        items = schedule_get.json().get('items') or []
        self.assertTrue(items)

        first_item = items[0]
        moved_start = timezone.now() + timedelta(days=3, hours=2)
        moved_end = moved_start + timedelta(hours=1)
        save_res = self.client.post(
            schedule_api_url,
            data={
                'items': [{
                    'id': first_item['id'],
                    'starts_at': moved_start.isoformat(),
                    'ends_at': moved_end.isoformat(),
                    'duration_minutes': 60,
                    'assigned_agent_id': self.agent1.id,
                    'notes': 'admin adjusted before lsa',
                    'status': first_item.get('status') or 'SCHEDULED',
                    'needs_admin_review': False,
                }]
            },
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(save_res.status_code, 200)

        reviewing_plan = ServiceSchedulePlan.objects.filter(
            submission=self.submission,
            status=ServiceSchedulePlan.Status.REVIEWING,
        ).order_by('-updated_at').first()
        self.assertIsNotNone(reviewing_plan)
        self.assertEqual(reviewing_plan.based_on_id, draft_plan.id)

        send_lsa_res = self.client.post(
            reverse('app_submission_review_schedule_send_lsa', kwargs={'submission_id': self.submission.id}),
            data={'agent_ids': [self.agent1.id, self.agent2.id]},
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(send_lsa_res.status_code, 200)
        send_payload = send_lsa_res.json()
        self.assertTrue(send_payload.get('ok'))
        batch_id = send_payload['batch_id']

        batch_review_page = self.client.get(
            reverse('app_submission_review_lsa_batch_review', kwargs={'submission_id': self.submission.id, 'batch_id': batch_id})
        )
        self.assertEqual(batch_review_page.status_code, 200)

        req1 = LsaAgentRequest.objects.get(batch_id=batch_id, target_agent=self.agent1)
        req2 = LsaAgentRequest.objects.get(batch_id=batch_id, target_agent=self.agent2)

        proposed1 = (req1.payload_snapshot or {}).get('proposed_schedule') or []
        self.assertTrue(proposed1)
        p1 = proposed1[0]
        suggested_start = timezone.now() + timedelta(days=4, hours=1)
        suggested_end = suggested_start + timedelta(hours=1)

        self.client.force_login(self.agent1)
        token1 = build_lsa_response_token(req1.id, self.agent1.id)
        agent1_res = self.client.post(
            reverse('agent_lsa_response_submit', kwargs={'request_id': req1.id}),
            data={
                'token': token1,
                'decision': 'PARTIAL',
                'note': 'can do alternate slot',
                'items': [{
                    'service_code': p1.get('service_code'),
                    'service_label': p1.get('service_label'),
                    'proposed_starts_at': p1.get('starts_at'),
                    'proposed_ends_at': p1.get('ends_at'),
                    'action': 'SUGGEST_CHANGE',
                    'suggested_starts_at': suggested_start.isoformat(),
                    'suggested_ends_at': suggested_end.isoformat(),
                    'note': 'shifted by selected agent',
                }],
            },
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(agent1_res.status_code, 200)
        response1_id = agent1_res.json()['response_id']

        self.client.force_login(self.agent2)
        token2 = build_lsa_response_token(req2.id, self.agent2.id)
        agent2_res = self.client.post(
            reverse('agent_lsa_response_submit', kwargs={'request_id': req2.id}),
            data={
                'token': token2,
                'decision': 'DECLINE',
                'note': 'unavailable',
                'items': [{
                    'service_code': p1.get('service_code'),
                    'service_label': p1.get('service_label'),
                    'proposed_starts_at': p1.get('starts_at'),
                    'proposed_ends_at': p1.get('ends_at'),
                    'action': 'UNAVAILABLE',
                    'note': 'cannot take this slot',
                }],
            },
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(agent2_res.status_code, 200)

        self.client.force_login(self.admin)
        select_res = self.client.post(
            reverse('app_submission_review_lsa_select_agent', kwargs={'submission_id': self.submission.id, 'batch_id': batch_id}),
            data={
                'request_id': req1.id,
                'response_id': response1_id,
                'note': 'best fit after comparison',
            },
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(select_res.status_code, 200)
        self.assertTrue(select_res.json().get('ok'))

        contract = LsaAgentContract.objects.get(batch_id=batch_id)
        self.assertEqual(contract.selected_agent_id, self.agent1.id)
        self.assertIsNotNone(contract.execution_schedule_plan_id)
        self.assertEqual(contract.execution_schedule_plan.status, ServiceSchedulePlan.Status.ACTIVE)

        req1.refresh_from_db()
        req2.refresh_from_db()
        self.assertEqual(req1.status, LsaAgentRequest.Status.SELECTED)
        self.assertEqual(req2.status, LsaAgentRequest.Status.NOT_SELECTED)

        execution_items = list(contract.execution_schedule_plan.items.all())
        self.assertTrue(execution_items)
        self.assertTrue(all(it.assigned_agent_id == self.agent1.id for it in execution_items if it.service_type == 'IN_PERSON_AGENT'))

        polite_non_selected = Message.objects.filter(
            conversation__survey_submission=self.submission,
            body__icontains='다른 Agent가 최종 선정',
        ).exists()
        self.assertTrue(polite_non_selected)

        contract_package_msg = Message.objects.filter(
            conversation__survey_submission=self.submission,
            body__icontains='계약 확정 안내',
        ).exists()
        self.assertTrue(contract_package_msg)

        conv = Conversation.objects.filter(survey_submission=self.submission).first()
        self.assertIsNotNone(conv)
        self.assertTrue(ConversationParticipant.objects.filter(conversation=conv, user=self.agent1).exists())
        joined_msg_exists = Message.objects.filter(conversation=conv, body__icontains='joined the thread').exists()
        contract_notice_exists = Message.objects.filter(conversation=conv, body__icontains='계약 확정 안내').exists()
        self.assertTrue(joined_msg_exists or contract_notice_exists)

        admin_cal = self.client.get(schedule_api_url, {'view': 'month', 'q': 'svc_step11_in_person'})
        self.assertEqual(admin_cal.status_code, 200)
        admin_items = admin_cal.json().get('items') or []
        self.assertTrue(admin_items)
        self.assertTrue(all('recommendation_source' in row for row in admin_items))

        self.client.force_login(self.agent1)
        agent_dashboard = self.client.get(reverse('app_agent_dashboard'))
        self.assertEqual(agent_dashboard.status_code, 200)
        self.assertContains(agent_dashboard, 'svc_step11_in_person')

        safe_schedule = get_schedule_for_display(self.customer)
        self.assertTrue(safe_schedule)
        first_day = next(iter(safe_schedule.keys()))
        customer_item = safe_schedule[first_day][0]
        self.assertNotIn('notes', customer_item)
        self.assertNotIn('source_reason', customer_item)
        self.assertNotIn('agent_id', customer_item)
