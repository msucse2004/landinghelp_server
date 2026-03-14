from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from settlement.models import ServiceScheduleItem, ServiceSchedulePlan
from survey.models import SurveySubmission


User = get_user_model()


class AdminScheduleWorkspaceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_schedule_ws',
            email='admin_schedule_ws@test.com',
            password='adminpass123',
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='customer_schedule_ws',
            email='customer_schedule_ws@test.com',
            password='custpass123',
        )
        self.agent = User.objects.create_user(
            username='agent_schedule_ws',
            email='agent_schedule_ws@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
        )

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={},
            requested_required_services=['svc_ws'],
        )
        self.plan = ServiceSchedulePlan.objects.create(
            submission=self.submission,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.DRAFT,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=1,
            created_by=self.admin,
            updated_by=self.admin,
        )
        self.item = ServiceScheduleItem.objects.create(
            schedule_plan=self.plan,
            service_code='svc_ws',
            service_label='Workspace Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=timezone.now() + timedelta(days=1),
            ends_at=timezone.now() + timedelta(days=1, hours=1),
            duration_minutes=60,
            assigned_agent=self.agent,
            status=ServiceScheduleItem.ItemStatus.SCHEDULED,
            source_score=88.5,
            source_reason='historical pattern: n=4',
            recommendation_source='historical',
            needs_admin_review=True,
            recommendation_metadata={
                'confidence_score': 88.5,
                'evidence_type': 'historical-match',
                'similar_historical_sample_count': 4,
                'suggested_day_offset_from_entry': 3,
            },
        )

    def _page_url(self):
        return reverse('app_submission_review_schedule', kwargs={'submission_id': self.submission.id})

    def _api_url(self):
        return reverse('app_submission_review_schedule_api', kwargs={'submission_id': self.submission.id})

    def test_admin_can_load_draft_workspace(self):
        self.client.force_login(self.admin)

        response = self.client.get(self._page_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'system_draft')

        api = self.client.get(self._api_url())
        self.assertEqual(api.status_code, 200)
        payload = api.json()
        self.assertEqual(payload['plan']['status'], ServiceSchedulePlan.Status.DRAFT)
        self.assertEqual(payload['plan']['stage_key'], 'system_draft')

    def test_admin_can_save_card_moves(self):
        self.client.force_login(self.admin)
        new_start = timezone.now() + timedelta(days=2, hours=2)
        new_end = new_start + timedelta(minutes=90)

        response = self.client.post(
            self._api_url(),
            data={
                'items': [{
                    'id': self.item.id,
                    'starts_at': new_start.isoformat(),
                    'ends_at': new_end.isoformat(),
                    'duration_minutes': 90,
                    'assigned_agent_id': self.agent.id,
                    'notes': 'moved by admin',
                    'status': ServiceScheduleItem.ItemStatus.SCHEDULED,
                    'needs_admin_review': True,
                }]
            },
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.status, ServiceSchedulePlan.Status.DRAFT)

        review_plan = ServiceSchedulePlan.objects.filter(
            submission=self.submission,
            status=ServiceSchedulePlan.Status.REVIEWING,
        ).order_by('-updated_at').first()
        self.assertIsNotNone(review_plan)
        review_item = review_plan.items.filter(based_on_item=self.item).first()
        self.assertIsNotNone(review_item)
        self.assertEqual(review_item.duration_minutes, 90)
        self.assertEqual(review_item.notes, 'moved by admin')
        self.assertEqual(review_item.assigned_agent_id, self.agent.id)

    def test_non_admin_cannot_access_workspace(self):
        self.client.force_login(self.customer)

        page = self.client.get(self._page_url())
        api = self.client.get(self._api_url())

        self.assertEqual(page.status_code, 302)
        self.assertEqual(api.status_code, 302)

    def test_recommendation_metadata_persists_after_edit(self):
        self.client.force_login(self.admin)
        moved_start = timezone.now() + timedelta(days=3)
        moved_end = moved_start + timedelta(hours=1)

        response = self.client.post(
            self._api_url(),
            data={
                'items': [{
                    'id': self.item.id,
                    'starts_at': moved_start.isoformat(),
                    'ends_at': moved_end.isoformat(),
                    'duration_minutes': 60,
                    'assigned_agent_id': self.agent.id,
                    'notes': 'metadata-preserve-check',
                    'status': ServiceScheduleItem.ItemStatus.SCHEDULED,
                    'needs_admin_review': True,
                }]
            },
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        review_plan = ServiceSchedulePlan.objects.filter(
            submission=self.submission,
            status=ServiceSchedulePlan.Status.REVIEWING,
        ).order_by('-updated_at').first()
        self.assertIsNotNone(review_plan)
        review_item = review_plan.items.filter(based_on_item=self.item).first()
        self.assertIsNotNone(review_item)
        self.assertEqual(float(review_item.source_score), 88.5)
        self.assertEqual(review_item.source_reason, 'historical pattern: n=4')
        self.assertEqual(review_item.recommendation_source, 'historical')
        self.assertTrue(review_item.needs_admin_review)
        self.assertEqual(review_item.recommendation_metadata.get('evidence_type'), 'historical-match')
        self.assertEqual(review_item.recommendation_metadata.get('similar_historical_sample_count'), 4)

    def test_invalid_datetime_is_rejected(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            self._api_url(),
            data={
                'items': [{
                    'id': self.item.id,
                    'starts_at': 'invalid-date',
                    'ends_at': (timezone.now() + timedelta(days=1)).isoformat(),
                    'duration_minutes': 60,
                    'assigned_agent_id': self.agent.id,
                    'notes': 'bad payload',
                    'status': ServiceScheduleItem.ItemStatus.SCHEDULED,
                }]
            },
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 400)
