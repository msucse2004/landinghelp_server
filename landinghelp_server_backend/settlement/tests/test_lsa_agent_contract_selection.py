from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from settlement.models import (
    LsaAgentContract,
    LsaAgentRequest,
    LsaAgentResponse,
    LsaAgentResponseItem,
    LsaSourcingBatch,
    ServiceSchedulePlan,
)
from survey.models import SurveySubmission


User = get_user_model()


class LsaAgentContractSelectionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_select',
            email='admin_select@test.com',
            password='adminpass123',
            role=User.Role.ADMIN,
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='customer_select',
            email='customer_select@test.com',
            password='custpass123',
        )
        self.agent1 = User.objects.create_user(
            username='agent_select_1',
            email='agent_select_1@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )
        self.agent2 = User.objects.create_user(
            username='agent_select_2',
            email='agent_select_2@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={},
            requested_required_services=['svc_contract'],
        )
        self.plan = ServiceSchedulePlan.objects.create(
            submission=self.submission,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.FINALIZED,
            source=ServiceSchedulePlan.Source.ADMIN,
            version=3,
            created_by=self.admin,
            updated_by=self.admin,
        )

        schedule_snapshot = [{
            'service_code': 'svc_contract',
            'service_label': 'Contract Service',
            'starts_at': (timezone.now() + timedelta(days=2)).isoformat(),
            'ends_at': (timezone.now() + timedelta(days=2, hours=1)).isoformat(),
        }]
        pricing_snapshot = [{'service_code': 'svc_contract', 'service_label': 'Contract Service', 'internal_agent_price': 150.0, 'currency': 'USD'}]

        self.batch = LsaSourcingBatch.objects.create(
            submission=self.submission,
            schedule_plan=self.plan,
            schedule_version=3,
            proposed_schedule_snapshot=schedule_snapshot,
            requested_services_snapshot=[{'code': 'svc_contract', 'label': 'Contract Service'}],
            internal_pricing_snapshot=pricing_snapshot,
            created_by=self.admin,
        )
        self.req1 = LsaAgentRequest.objects.create(
            batch=self.batch,
            target_agent=self.agent1,
            status=LsaAgentRequest.Status.RESPONDED,
            payload_snapshot={'proposed_schedule': schedule_snapshot},
            responded_at=timezone.now(),
        )
        self.req2 = LsaAgentRequest.objects.create(
            batch=self.batch,
            target_agent=self.agent2,
            status=LsaAgentRequest.Status.RESPONDED,
            payload_snapshot={'proposed_schedule': schedule_snapshot},
            responded_at=timezone.now(),
        )
        self.resp1 = LsaAgentResponse.objects.create(
            request=self.req1,
            responded_by=self.agent1,
            decision=LsaAgentResponse.Decision.ACCEPT_AS_IS,
            note='ok',
            revision=1,
        )
        self.resp2 = LsaAgentResponse.objects.create(
            request=self.req2,
            responded_by=self.agent2,
            decision=LsaAgentResponse.Decision.PARTIAL,
            note='can adjust',
            revision=1,
        )
        LsaAgentResponseItem.objects.create(
            response=self.resp1,
            service_code='svc_contract',
            service_label='Contract Service',
            action=LsaAgentResponseItem.Action.ACCEPT,
        )
        LsaAgentResponseItem.objects.create(
            response=self.resp2,
            service_code='svc_contract',
            service_label='Contract Service',
            action=LsaAgentResponseItem.Action.SUGGEST_CHANGE,
            suggested_starts_at=timezone.now() + timedelta(days=3),
            suggested_ends_at=timezone.now() + timedelta(days=3, hours=1),
        )

    def _select_url(self):
        return reverse('app_submission_review_lsa_select_agent', kwargs={'submission_id': self.submission.id, 'batch_id': self.batch.id})

    def _post_select(self, request_id, response_id):
        self.client.force_login(self.admin)
        return self.client.post(
            self._select_url(),
            data={'request_id': request_id, 'response_id': response_id, 'note': 'final choice'},
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

    def test_only_one_selection_per_sourcing_batch(self):
        res = self._post_select(self.req1.id, self.resp1.id)
        self.assertEqual(res.status_code, 200)
        self.batch.refresh_from_db()
        self.req1.refresh_from_db()
        self.req2.refresh_from_db()

        self.assertEqual(self.req1.status, LsaAgentRequest.Status.SELECTED)
        self.assertEqual(self.req2.status, LsaAgentRequest.Status.NOT_SELECTED)
        self.assertEqual(LsaAgentContract.objects.filter(batch=self.batch).count(), 1)

    def test_invalid_repeat_selection_blocked(self):
        first = self._post_select(self.req1.id, self.resp1.id)
        self.assertEqual(first.status_code, 200)
        second = self._post_select(self.req2.id, self.resp2.id)
        self.assertEqual(second.status_code, 409)
        self.assertIn('이미 Agent가 선정된 배치입니다', second.json().get('error', ''))

    def test_unrelated_response_cannot_be_selected(self):
        other_customer = User.objects.create_user(
            username='customer_select_other',
            email='customer_select_other@test.com',
            password='custpass123',
        )
        other_submission = SurveySubmission.objects.create(
            user=other_customer,
            email='other_submission@test.com',
            status=SurveySubmission.Status.SUBMITTED,
            answers={},
            requested_required_services=['svc_contract'],
        )
        other_plan = ServiceSchedulePlan.objects.create(
            submission=other_submission,
            customer=other_customer,
            status=ServiceSchedulePlan.Status.FINALIZED,
            source=ServiceSchedulePlan.Source.ADMIN,
            version=1,
            created_by=self.admin,
            updated_by=self.admin,
        )
        other_batch = LsaSourcingBatch.objects.create(
            submission=other_submission,
            schedule_plan=other_plan,
            schedule_version=1,
            proposed_schedule_snapshot=[],
            requested_services_snapshot=[],
            internal_pricing_snapshot=[],
            created_by=self.admin,
        )
        other_req = LsaAgentRequest.objects.create(
            batch=other_batch,
            target_agent=self.agent1,
            status=LsaAgentRequest.Status.RESPONDED,
            payload_snapshot={},
            responded_at=timezone.now(),
        )
        other_resp = LsaAgentResponse.objects.create(
            request=other_req,
            responded_by=self.agent1,
            decision=LsaAgentResponse.Decision.ACCEPT_AS_IS,
            revision=1,
        )

        res = self._post_select(self.req1.id, other_resp.id)
        self.assertEqual(res.status_code, 409)
        self.assertIn('선택 응답이 해당 요청에 속하지 않습니다', res.json().get('error', ''))

    def test_batch_closes_correctly_after_selection(self):
        res = self._post_select(self.req2.id, self.resp2.id)
        self.assertEqual(res.status_code, 200)
        self.batch.refresh_from_db()

        self.assertEqual(self.batch.selected_request_id, self.req2.id)
        self.assertIsNotNone(self.batch.selected_at)
        self.assertIsNotNone(self.batch.closed_at)
        contract = LsaAgentContract.objects.get(batch=self.batch)
        self.assertEqual(contract.selected_agent_id, self.agent2.id)

    def test_incomplete_identity_verification_request_cannot_be_selected(self):
        self.req1.status = LsaAgentRequest.Status.SENT
        self.req1.save(update_fields=['status'])

        res = self._post_select(self.req1.id, self.resp1.id)
        self.assertEqual(res.status_code, 409)
        self.assertIn('필수 신분 확인 서류 업로드까지 완료된 응답만 선정할 수 있습니다.', res.json().get('error', ''))

    def test_hq_staff_cannot_select_final_agent(self):
        hq_staff = User.objects.create_user(
            username='hq_select_denied',
            email='hq_select_denied@test.com',
            password='pass1234',
            role=User.Role.HQ_STAFF,
            is_staff=True,
        )
        self.client.force_login(hq_staff)
        response = self.client.post(
            self._select_url(),
            data={'request_id': self.req1.id, 'response_id': self.resp1.id, 'note': 'not allowed'},
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 403)
