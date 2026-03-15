from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from settlement.models import ServiceScheduleItem, ServiceSchedulePlan
from survey.models import SurveySubmission


User = get_user_model()


class ScheduleDraftVersioningTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_ver',
            email='admin_ver@test.com',
            password='adminpass123',
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='cust_ver',
            email='cust_ver@test.com',
            password='custpass123',
        )
        self.agent = User.objects.create_user(
            username='agent_ver',
            email='agent_ver@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
        )
        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={},
            requested_required_services=['svc_ver'],
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
            service_code='svc_ver',
            service_label='Version Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=timezone.now() + timedelta(days=1),
            ends_at=timezone.now() + timedelta(days=1, hours=1),
            duration_minutes=60,
            assigned_agent=self.agent,
            status=ServiceScheduleItem.ItemStatus.SCHEDULED,
            recommendation_source='historical',
            needs_admin_review=True,
        )

    def _api_url(self):
        return reverse('app_submission_review_schedule_api', kwargs={'submission_id': self.submission.id})

    def _save_payload(self, item_id, minutes=60):
        start = timezone.now() + timedelta(days=2)
        end = start + timedelta(minutes=minutes)
        return {
            'items': [{
                'id': item_id,
                'starts_at': start.isoformat(),
                'ends_at': end.isoformat(),
                'duration_minutes': minutes,
                'assigned_agent_id': self.agent.id,
                'notes': 'version save',
                'status': ServiceScheduleItem.ItemStatus.SCHEDULED,
                'needs_admin_review': True,
            }]
        }

    def test_system_draft_creation_exists(self):
        self.assertEqual(self.system_plan.status, ServiceSchedulePlan.Status.DRAFT)
        self.assertEqual(self.system_plan.source, ServiceSchedulePlan.Source.HYBRID)
        self.assertIsNone(self.system_plan.based_on_id)

    def test_admin_revision_save_creates_reviewing_version(self):
        self.client.force_login(self.admin)
        res = self.client.post(
            self._api_url(),
            data=self._save_payload(self.system_item.id, minutes=75),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(res.status_code, 200)

        review_plan = ServiceSchedulePlan.objects.filter(
            submission=self.submission,
            status=ServiceSchedulePlan.Status.REVIEWING,
        ).first()
        self.assertIsNotNone(review_plan)
        self.assertEqual(review_plan.based_on_id, self.system_plan.id)
        review_item = review_plan.items.filter(based_on_item_id=self.system_item.id).first()
        self.assertIsNotNone(review_item)
        self.assertEqual(review_item.duration_minutes, 75)

    def test_multiple_saves_update_same_reviewing_version(self):
        self.client.force_login(self.admin)
        res1 = self.client.post(
            self._api_url(),
            data=self._save_payload(self.system_item.id, minutes=70),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(res1.status_code, 200)
        review_plan = ServiceSchedulePlan.objects.get(
            submission=self.submission,
            status=ServiceSchedulePlan.Status.REVIEWING,
        )
        review_item = review_plan.items.get(based_on_item_id=self.system_item.id)

        res2 = self.client.post(
            self._api_url(),
            data=self._save_payload(review_item.id, minutes=95),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(res2.status_code, 200)

        self.assertEqual(
            ServiceSchedulePlan.objects.filter(submission=self.submission, status=ServiceSchedulePlan.Status.REVIEWING).count(),
            1,
        )
        review_item.refresh_from_db()
        self.assertEqual(review_item.duration_minutes, 95)

    def test_sent_or_finalized_plan_is_protected(self):
        self.client.force_login(self.admin)
        self.system_plan.status = ServiceSchedulePlan.Status.SENT
        self.system_plan.save(update_fields=['status'])

        res = self.client.post(
            self._api_url(),
            data=self._save_payload(self.system_item.id),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(res.status_code, 409)
