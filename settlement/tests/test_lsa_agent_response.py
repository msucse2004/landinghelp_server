from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from settlement.lsa_service import build_lsa_response_token
from settlement.models import (
    LsaAgentRequest,
    LsaAgentResponse,
    LsaAgentResponseItem,
    LsaSourcingBatch,
    ServiceSchedulePlan,
)
from survey.models import SurveySubmission


User = get_user_model()


class LsaAgentResponseWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_resp',
            email='admin_resp@test.com',
            password='adminpass123',
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='customer_resp',
            email='customer_resp@test.com',
            password='custpass123',
        )
        self.agent = User.objects.create_user(
            username='agent_resp',
            email='agent_resp@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )
        self.other_agent = User.objects.create_user(
            username='agent_other_resp',
            email='agent_other_resp@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={},
            requested_required_services=['svc_resp'],
        )
        self.plan = ServiceSchedulePlan.objects.create(
            submission=self.submission,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.REVIEWING,
            source=ServiceSchedulePlan.Source.ADMIN,
            version=2,
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.batch = LsaSourcingBatch.objects.create(
            submission=self.submission,
            schedule_plan=self.plan,
            schedule_version=2,
            proposed_schedule_snapshot=[{
                'service_code': 'svc_resp',
                'service_label': 'Response Service',
                'starts_at': (timezone.now() + timedelta(days=2)).isoformat(),
                'ends_at': (timezone.now() + timedelta(days=2, hours=1)).isoformat(),
            }],
            requested_services_snapshot=[{'code': 'svc_resp', 'label': 'Response Service'}],
            internal_pricing_snapshot=[{'service_code': 'svc_resp', 'internal_agent_price': 123.0, 'currency': 'USD'}],
            created_by=self.admin,
        )
        self.req = LsaAgentRequest.objects.create(
            batch=self.batch,
            target_agent=self.agent,
            status=LsaAgentRequest.Status.SENT,
            payload_snapshot={
                'proposed_schedule': self.batch.proposed_schedule_snapshot,
                'requested_services': self.batch.requested_services_snapshot,
                'internal_service_pricing': self.batch.internal_pricing_snapshot,
                'proposed_schedule_version': 2,
            },
        )

    def _submit_url(self):
        return reverse('agent_lsa_response_submit', kwargs={'request_id': self.req.id})

    def _post(self, user, decision, items):
        self.client.force_login(user)
        token = build_lsa_response_token(self.req.id, self.agent.id)
        return self.client.post(
            self._submit_url(),
            data={
                'token': token,
                'decision': decision,
                'note': 'agent note',
                'items': items,
            },
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

    def test_accept_as_is_flow(self):
        p = self.batch.proposed_schedule_snapshot[0]
        res = self._post(self.agent, 'ACCEPT_AS_IS', [{
            'service_code': 'svc_resp',
            'service_label': 'Response Service',
            'proposed_starts_at': p['starts_at'],
            'proposed_ends_at': p['ends_at'],
            'action': 'ACCEPT',
        }])
        self.assertEqual(res.status_code, 200)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, LsaAgentRequest.Status.RESPONDED)
        resp = self.req.responses.order_by('-revision').first()
        self.assertEqual(resp.decision, LsaAgentResponse.Decision.ACCEPT_AS_IS)

    def test_suggest_change_flow(self):
        p = self.batch.proposed_schedule_snapshot[0]
        new_start = timezone.now() + timedelta(days=3)
        new_end = new_start + timedelta(hours=1)
        res = self._post(self.agent, 'PARTIAL', [{
            'service_code': 'svc_resp',
            'service_label': 'Response Service',
            'proposed_starts_at': p['starts_at'],
            'proposed_ends_at': p['ends_at'],
            'action': 'SUGGEST_CHANGE',
            'suggested_starts_at': new_start.isoformat(),
            'suggested_ends_at': new_end.isoformat(),
            'note': 'can do later',
        }])
        self.assertEqual(res.status_code, 200)
        resp = self.req.responses.order_by('-revision').first()
        item = resp.items.first()
        self.assertEqual(resp.decision, LsaAgentResponse.Decision.PARTIAL)
        self.assertEqual(item.action, LsaAgentResponseItem.Action.SUGGEST_CHANGE)
        self.assertIsNotNone(item.suggested_starts_at)

    def test_decline_flow(self):
        p = self.batch.proposed_schedule_snapshot[0]
        res = self._post(self.agent, 'DECLINE', [{
            'service_code': 'svc_resp',
            'service_label': 'Response Service',
            'proposed_starts_at': p['starts_at'],
            'proposed_ends_at': p['ends_at'],
            'action': 'UNAVAILABLE',
            'note': 'not available',
        }])
        self.assertEqual(res.status_code, 200)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, LsaAgentRequest.Status.DECLINED)

    def test_only_invited_agent_can_respond(self):
        p = self.batch.proposed_schedule_snapshot[0]
        res = self._post(self.other_agent, 'ACCEPT_AS_IS', [{
            'service_code': 'svc_resp',
            'service_label': 'Response Service',
            'proposed_starts_at': p['starts_at'],
            'proposed_ends_at': p['ends_at'],
            'action': 'ACCEPT',
        }])
        self.assertEqual(res.status_code, 403)
