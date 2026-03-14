from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from settlement.lsa_service import send_lsa_batch_for_schedule_plan, select_lsa_agent_for_contract
from settlement.models import (
    LsaAgentRequest,
    LsaAgentResponse,
    LsaAgentResponseItem,
    LsaSourcingBatch,
    ServiceScheduleItem,
    ServiceSchedulePlan,
)
from survey.models import SurveySubmission


User = get_user_model()


class ScheduleLifecycleSeparationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='lifecycle_admin',
            email='lifecycle_admin@test.com',
            password='adminpass123',
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='lifecycle_customer',
            email='lifecycle_customer@test.com',
            password='custpass123',
        )
        self.agent = User.objects.create_user(
            username='lifecycle_agent',
            email='lifecycle_agent@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={},
            requested_required_services=['svc_lifecycle'],
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
        base_start = timezone.now() + timedelta(days=2)
        self.system_item = ServiceScheduleItem.objects.create(
            schedule_plan=self.system_plan,
            service_code='svc_lifecycle',
            service_label='Lifecycle Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=base_start,
            ends_at=base_start + timedelta(hours=1),
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
            service_code='svc_lifecycle',
            service_label='Lifecycle Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=base_start + timedelta(days=1),
            ends_at=base_start + timedelta(days=1, hours=1),
            duration_minutes=60,
            status=ServiceScheduleItem.ItemStatus.SCHEDULED,
            source_score=85,
            source_reason='admin-adjusted before send',
            recommendation_source='historical',
            needs_admin_review=True,
        )

    def test_correct_lifecycle_transitions(self):
        batch, requests = send_lsa_batch_for_schedule_plan(self.review_plan, [self.agent], actor=self.admin)

        self.assertEqual(len(requests), 1)
        self.review_plan.refresh_from_db()
        self.assertEqual(self.review_plan.status, ServiceSchedulePlan.Status.REVIEWING)

        self.assertEqual(batch.schedule_plan.status, ServiceSchedulePlan.Status.FINALIZED)
        self.assertEqual(batch.schedule_plan.based_on_id, self.review_plan.id)
        self.assertEqual(batch.schedule_plan.submission_id, self.submission.id)

    def test_sent_snapshot_immutable_after_working_edit(self):
        batch, _requests = send_lsa_batch_for_schedule_plan(self.review_plan, [self.agent], actor=self.admin)
        snapshot_plan = batch.schedule_plan
        snap_item = snapshot_plan.items.first()
        self.assertIsNotNone(snap_item)
        original_snapshot_start = snap_item.starts_at

        self.review_item.starts_at = self.review_item.starts_at + timedelta(days=7)
        self.review_item.ends_at = self.review_item.ends_at + timedelta(days=7)
        self.review_item.save(update_fields=['starts_at', 'ends_at'])

        snapshot_plan.refresh_from_db()
        snap_item_after = snapshot_plan.items.first()
        self.assertEqual(snap_item_after.starts_at, original_snapshot_start)

        batch.refresh_from_db()
        self.assertEqual(batch.proposed_schedule_snapshot[0]['starts_at'], original_snapshot_start.isoformat())

    def test_final_schedule_separated_from_working_draft(self):
        batch, requests = send_lsa_batch_for_schedule_plan(self.review_plan, [self.agent], actor=self.admin)
        req = requests[0]

        response = LsaAgentResponse.objects.create(
            request=req,
            responded_by=self.agent,
            decision=LsaAgentResponse.Decision.ACCEPT_AS_IS,
            note='ok',
            revision=1,
        )
        LsaAgentResponseItem.objects.create(
            response=response,
            service_code='svc_lifecycle',
            service_label='Lifecycle Service',
            proposed_starts_at=batch.schedule_plan.items.first().starts_at,
            proposed_ends_at=batch.schedule_plan.items.first().ends_at,
            action=LsaAgentResponseItem.Action.ACCEPT,
        )

        contract = select_lsa_agent_for_contract(
            batch_id=batch.id,
            request_id=req.id,
            response_id=response.id,
            actor=self.admin,
            note='select agent',
        )

        final_plan = contract.execution_schedule_plan
        self.assertIsNotNone(final_plan)
        self.assertEqual(final_plan.status, ServiceSchedulePlan.Status.ACTIVE)
        self.assertNotEqual(final_plan.id, self.review_plan.id)
        self.assertNotEqual(final_plan.id, batch.schedule_plan_id)
        self.assertEqual(final_plan.based_on_id, batch.schedule_plan_id)
