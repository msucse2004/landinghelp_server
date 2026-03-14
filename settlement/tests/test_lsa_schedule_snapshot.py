from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from settlement.models import (
    LsaAgentRequest,
    LsaSourcingBatch,
    ServiceScheduleItem,
    ServiceSchedulePlan,
    SettlementService,
)
from survey.models import SurveySubmission


User = get_user_model()


class LsaScheduleSnapshotTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_lsa',
            email='admin_lsa@test.com',
            password='adminpass123',
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='customer_lsa',
            email='customer_lsa@test.com',
            password='custpass123',
        )
        self.agent1 = User.objects.create_user(
            username='agent_lsa_1',
            email='agent_lsa_1@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
            agent_states=['NC'],
        )
        self.agent2 = User.objects.create_user(
            username='agent_lsa_2',
            email='agent_lsa_2@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
            agent_states=['NC'],
        )

        SettlementService.objects.create(
            code='svc_lsa',
            name='LSA Service',
            category=SettlementService.Category.ADMIN,
            required_time=60,
            customer_price=500,
            agent_price=321,
            is_active=True,
        )

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={'region': 'North Carolina'},
            requested_required_services=['svc_lsa'],
        )

        self.system_plan = ServiceSchedulePlan.objects.create(
            submission=self.submission,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.DRAFT,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=1,
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.system_item = ServiceScheduleItem.objects.create(
            schedule_plan=self.system_plan,
            service_code='svc_lsa',
            service_label='LSA Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=timezone.now() + timedelta(days=2),
            ends_at=timezone.now() + timedelta(days=2, hours=1),
            duration_minutes=60,
            status=ServiceScheduleItem.ItemStatus.SCHEDULED,
            recommendation_source='historical',
            needs_admin_review=True,
        )

        self.review_plan = ServiceSchedulePlan.objects.create(
            submission=self.submission,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.REVIEWING,
            source=ServiceSchedulePlan.Source.ADMIN,
            version=2,
            based_on=self.system_plan,
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.review_item = ServiceScheduleItem.objects.create(
            schedule_plan=self.review_plan,
            based_on_item=self.system_item,
            service_code='svc_lsa',
            service_label='LSA Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=timezone.now() + timedelta(days=3),
            ends_at=timezone.now() + timedelta(days=3, hours=1),
            duration_minutes=60,
            status=ServiceScheduleItem.ItemStatus.SCHEDULED,
            source_score=82.3,
            source_reason='admin-adjusted',
            recommendation_source='historical',
            needs_admin_review=True,
        )

    def _send_url(self):
        return reverse('app_submission_review_schedule_send_lsa', kwargs={'submission_id': self.submission.id})

    def _post_send(self, agent_ids):
        self.client.force_login(self.admin)
        return self.client.post(
            self._send_url(),
            data={'agent_ids': agent_ids},
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

    def test_lsa_references_correct_schedule_snapshot(self):
        res = self._post_send([self.agent1.id])
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertTrue(payload.get('ok'))

        batch = LsaSourcingBatch.objects.get(id=payload['batch_id'])
        self.assertNotEqual(batch.schedule_plan_id, self.review_plan.id)
        self.assertEqual(batch.schedule_plan.status, ServiceSchedulePlan.Status.FINALIZED)
        self.assertEqual(batch.schedule_plan.based_on_id, self.review_plan.id)
        self.assertGreater(batch.schedule_version, self.review_plan.version)
        self.review_plan.refresh_from_db()
        self.assertEqual(self.review_plan.status, ServiceSchedulePlan.Status.REVIEWING)
        self.assertTrue(batch.proposed_schedule_snapshot)
        first = batch.proposed_schedule_snapshot[0]
        self.assertEqual(first.get('service_code'), 'svc_lsa')
        self.assertEqual(first.get('recommendation_source'), 'historical')

    def test_multiple_candidate_agents_receive_same_adjusted_draft(self):
        res = self._post_send([self.agent1.id, self.agent2.id])
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertEqual(payload.get('sent_count'), 2)

        batch = LsaSourcingBatch.objects.get(id=payload['batch_id'])
        requests = list(LsaAgentRequest.objects.filter(batch=batch).order_by('target_agent_id'))
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].payload_snapshot['proposed_schedule_version'], batch.schedule_version)
        self.assertEqual(requests[1].payload_snapshot['proposed_schedule_version'], batch.schedule_version)
        self.assertGreater(batch.schedule_version, self.review_plan.version)
        self.assertEqual(
            requests[0].payload_snapshot['proposed_schedule'],
            requests[1].payload_snapshot['proposed_schedule'],
        )

    def test_post_send_admin_edits_do_not_mutate_historical_payload(self):
        res = self._post_send([self.agent1.id])
        self.assertEqual(res.status_code, 200)
        batch = LsaSourcingBatch.objects.get(id=res.json()['batch_id'])
        snapshot_before = list(batch.proposed_schedule_snapshot)
        snapshot_plan = batch.schedule_plan
        snapshot_item_before = snapshot_plan.items.order_by('id').first()
        self.assertIsNotNone(snapshot_item_before)
        snapshot_item_before_start = snapshot_item_before.starts_at

        self.review_item.starts_at = timezone.now() + timedelta(days=10)
        self.review_item.ends_at = self.review_item.starts_at + timedelta(hours=2)
        self.review_item.save(update_fields=['starts_at', 'ends_at'])

        batch.refresh_from_db()
        req = LsaAgentRequest.objects.filter(batch=batch, target_agent=self.agent1).first()
        self.assertEqual(batch.proposed_schedule_snapshot, snapshot_before)
        self.assertEqual(req.payload_snapshot['proposed_schedule'], snapshot_before)

        snapshot_plan.refresh_from_db()
        snapshot_item_after = snapshot_plan.items.order_by('id').first()
        self.assertEqual(snapshot_item_after.starts_at, snapshot_item_before_start)

    def test_lsa_package_contains_customer_safe_services_schedule_and_pricing(self):
        res = self._post_send([self.agent1.id])
        self.assertEqual(res.status_code, 200)

        batch = LsaSourcingBatch.objects.get(id=res.json()['batch_id'])
        req = LsaAgentRequest.objects.get(batch=batch, target_agent=self.agent1)
        payload = req.payload_snapshot

        self.assertIn('customer_safe_info', payload)
        self.assertIn('requested_services', payload)
        self.assertIn('proposed_schedule', payload)
        self.assertIn('internal_service_pricing', payload)

        self.assertEqual(payload['customer_safe_info'].get('submission_id'), self.submission.id)
        self.assertTrue(payload['requested_services'])
        self.assertEqual(payload['requested_services'][0].get('code'), 'svc_lsa')
        self.assertTrue(payload['proposed_schedule'])
        self.assertEqual(payload['proposed_schedule'][0].get('service_code'), 'svc_lsa')

        self.assertTrue(payload['internal_service_pricing'])
        first_price = payload['internal_service_pricing'][0]
        self.assertEqual(first_price.get('service_code'), 'svc_lsa')
        self.assertEqual(first_price.get('internal_agent_price'), 321.0)

        self.assertEqual(payload.get('proposed_schedule_plan_id'), batch.schedule_plan_id)
        self.assertEqual(payload.get('based_on_schedule_plan_id'), self.review_plan.id)
        self.assertEqual(payload.get('root_recommended_schedule_plan_id'), self.system_plan.id)
