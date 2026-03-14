from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from messaging.models import ConversationParticipant, Message
from settlement.lsa_service import (
    _expand_existing_shared_conversation_for_contract,
    select_lsa_agent_for_contract,
)
from settlement.models import (
    LsaAgentContract,
    LsaAgentRequest,
    LsaAgentResponse,
    LsaAgentResponseItem,
    LsaSourcingBatch,
    ServiceSchedulePlan,
)
from settlement.notifications import _get_or_create_shared_conversation
from survey.models import SurveySubmission


User = get_user_model()


class LsaContractNotificationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_notify',
            email='admin_notify@test.com',
            password='adminpass123',
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='customer_notify',
            email='customer_notify@test.com',
            password='custpass123',
        )
        self.selected_agent = User.objects.create_user(
            username='agent_selected_notify',
            email='agent_selected_notify@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )
        self.other_agent = User.objects.create_user(
            username='agent_other_notify',
            email='agent_other_notify@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={},
            requested_required_services=['svc_notify'],
        )
        self.plan = ServiceSchedulePlan.objects.create(
            submission=self.submission,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.FINALIZED,
            source=ServiceSchedulePlan.Source.ADMIN,
            version=1,
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.plan.items.create(
            service_code='svc_notify',
            service_label='Notify Service',
            service_type='IN_PERSON_AGENT',
            starts_at=timezone.now() + timedelta(days=2),
            ends_at=timezone.now() + timedelta(days=2, hours=1),
            duration_minutes=60,
            status='SCHEDULED',
            recommendation_source='historical',
            source_reason='negotiation detail',
            notes='internal note',
        )

        self.batch = LsaSourcingBatch.objects.create(
            submission=self.submission,
            schedule_plan=self.plan,
            schedule_version=1,
            proposed_schedule_snapshot=[{
                'service_code': 'svc_notify',
                'service_label': 'Notify Service',
                'starts_at': (timezone.now() + timedelta(days=2)).isoformat(),
                'ends_at': (timezone.now() + timedelta(days=2, hours=1)).isoformat(),
            }],
            requested_services_snapshot=[{'code': 'svc_notify', 'label': 'Notify Service'}],
            internal_pricing_snapshot=[{'service_code': 'svc_notify', 'internal_agent_price': 220.0, 'currency': 'USD'}],
            created_by=self.admin,
        )
        self.req_selected = LsaAgentRequest.objects.create(
            batch=self.batch,
            target_agent=self.selected_agent,
            status=LsaAgentRequest.Status.RESPONDED,
            payload_snapshot={},
            responded_at=timezone.now(),
        )
        self.req_other = LsaAgentRequest.objects.create(
            batch=self.batch,
            target_agent=self.other_agent,
            status=LsaAgentRequest.Status.RESPONDED,
            payload_snapshot={},
            responded_at=timezone.now(),
        )
        self.resp_selected = LsaAgentResponse.objects.create(
            request=self.req_selected,
            responded_by=self.selected_agent,
            decision=LsaAgentResponse.Decision.ACCEPT_AS_IS,
            revision=1,
        )
        self.resp_other = LsaAgentResponse.objects.create(
            request=self.req_other,
            responded_by=self.other_agent,
            decision=LsaAgentResponse.Decision.ACCEPT_AS_IS,
            revision=1,
        )
        LsaAgentResponseItem.objects.create(
            response=self.resp_selected,
            service_code='svc_notify',
            service_label='Notify Service',
            action=LsaAgentResponseItem.Action.ACCEPT,
        )

    @patch('django.core.mail.send_mail')
    @patch('settlement.notifications._is_email_configured', return_value=True)
    def test_selected_nonselected_and_contract_delivery_notifications(self, _email_cfg, mock_send_mail):
        contract = select_lsa_agent_for_contract(
            batch_id=self.batch.id,
            request_id=self.req_selected.id,
            response_id=self.resp_selected.id,
            actor=self.admin,
            note='pick selected',
        )
        self.assertTrue(isinstance(contract, LsaAgentContract))

        recipients = [tuple(call.args[3]) for call in mock_send_mail.mock_calls if len(call.args) >= 4]
        self.assertIn((self.selected_agent.email,), recipients)
        self.assertIn((self.other_agent.email,), recipients)

        conv = _get_or_create_shared_conversation(self.submission, subject_fallback='정착 서비스')
        selected_msgs = Message.objects.filter(conversation=conv, body__icontains='계약 확정 안내').count()
        non_selected_msgs = Message.objects.filter(conversation=conv, body__icontains='다른 Agent가 최종 선정').count()
        self.assertGreaterEqual(selected_msgs, 1)
        self.assertGreaterEqual(non_selected_msgs, 1)

    @patch('django.core.mail.send_mail')
    @patch('settlement.notifications._is_email_configured', return_value=True)
    def test_existing_conversation_expansion_and_system_join_message(self, _email_cfg, _mock_send_mail):
        conv = _get_or_create_shared_conversation(self.submission, subject_fallback='기존 스레드')
        before_count = ConversationParticipant.objects.filter(conversation=conv).count()

        contract = select_lsa_agent_for_contract(
            batch_id=self.batch.id,
            request_id=self.req_selected.id,
            response_id=self.resp_selected.id,
            actor=self.admin,
        )

        after_count = ConversationParticipant.objects.filter(conversation=conv).count()
        self.assertGreaterEqual(after_count, before_count + 1)
        self.assertTrue(
            ConversationParticipant.objects.filter(conversation=conv, user=self.selected_agent).exists()
        )
        self.assertTrue(
            Message.objects.filter(conversation=conv, body__icontains='joined the thread').exists()
        )

        _expand_existing_shared_conversation_for_contract(contract)
        participant_count_second = ConversationParticipant.objects.filter(conversation=conv, user=self.selected_agent).count()
        join_message_count = Message.objects.filter(conversation=conv, body__icontains='joined the thread').count()
        self.assertEqual(participant_count_second, 1)
        self.assertEqual(join_message_count, 1)

    @patch('django.core.mail.send_mail')
    @patch('settlement.notifications._is_email_configured', return_value=True)
    def test_contract_delivery_path_contains_execution_plan_reference(self, _email_cfg, _mock_send_mail):
        contract = select_lsa_agent_for_contract(
            batch_id=self.batch.id,
            request_id=self.req_selected.id,
            response_id=self.resp_selected.id,
            actor=self.admin,
        )
        self.assertIsNotNone(contract.execution_schedule_plan_id)

        conv = _get_or_create_shared_conversation(self.submission, subject_fallback='정착 서비스')
        contract_msg = Message.objects.filter(
            conversation=conv,
            body__icontains=f'Execution plan #{contract.execution_schedule_plan_id}',
        ).exists()
        self.assertTrue(contract_msg)
