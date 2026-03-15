from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from settlement.models import ServiceScheduleItem, ServiceSchedulePlan, UserSettlementPlan
from settlement.schedule_utils import get_schedule_for_display
from survey.models import SurveySubmission


User = get_user_model()


class CalendarWorkbenchAndRoleVisibilityTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_cal',
            email='admin_cal@test.com',
            password='adminpass123',
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='customer_cal',
            email='customer_cal@test.com',
            password='custpass123',
        )
        self.agent = User.objects.create_user(
            username='agent_cal',
            email='agent_cal@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )
        self.other_agent = User.objects.create_user(
            username='agent_cal_other',
            email='agent_cal_other@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={},
            requested_required_services=['svc_alpha', 'svc_beta'],
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
        start = timezone.now() + timedelta(days=1)
        ServiceScheduleItem.objects.create(
            schedule_plan=self.plan,
            service_code='svc_alpha',
            service_label='Alpha Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=start,
            ends_at=start + timedelta(hours=1),
            duration_minutes=60,
            assigned_agent=self.agent,
            status=ServiceScheduleItem.ItemStatus.SCHEDULED,
            recommendation_source='historical',
            source_reason='internal reason alpha',
            needs_admin_review=True,
            notes='internal notes alpha',
        )
        ServiceScheduleItem.objects.create(
            schedule_plan=self.plan,
            service_code='svc_beta',
            service_label='Beta Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=start + timedelta(days=1),
            ends_at=start + timedelta(days=1, hours=1),
            duration_minutes=60,
            assigned_agent=self.other_agent,
            status=ServiceScheduleItem.ItemStatus.SCHEDULED,
            recommendation_source='fallback',
            source_reason='internal reason beta',
            needs_admin_review=False,
            notes='internal notes beta',
        )

    def test_admin_workbench_api_supports_view_modes_and_search(self):
        self.client.force_login(self.admin)
        url = reverse('app_submission_review_schedule_api', kwargs={'submission_id': self.submission.id})

        for mode in ['day', 'week', 'month']:
            resp = self.client.get(url, {'view': mode, 'q': 'Alpha'})
            self.assertEqual(resp.status_code, 200)
            payload = resp.json()
            self.assertEqual(payload['calendar_view']['mode'], mode)
            labels = [r['service_label'] for r in payload['items']]
            self.assertIn('Alpha Service', labels)
            self.assertNotIn('Beta Service', labels)
            self.assertTrue(any('recommendation_source' in r for r in payload['items']))
            self.assertEqual(payload['plan']['stage_key'], 'admin_adjusted_draft')

    def test_agent_limited_view_shows_only_assigned_execution_items(self):
        exec_plan = ServiceSchedulePlan.objects.create(
            submission=self.submission,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.ACTIVE,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=3,
            based_on=self.plan,
            created_by=self.admin,
            updated_by=self.admin,
        )
        ServiceScheduleItem.objects.create(
            schedule_plan=exec_plan,
            service_code='svc_alpha',
            service_label='Alpha Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=timezone.now() + timedelta(days=2),
            ends_at=timezone.now() + timedelta(days=2, hours=1),
            duration_minutes=60,
            assigned_agent=self.agent,
            status=ServiceScheduleItem.ItemStatus.CONFIRMED,
            source_reason='do not show this',
            notes='do not show this either',
        )
        ServiceScheduleItem.objects.create(
            schedule_plan=exec_plan,
            service_code='svc_beta',
            service_label='Beta Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=timezone.now() + timedelta(days=2),
            ends_at=timezone.now() + timedelta(days=2, hours=1),
            duration_minutes=60,
            assigned_agent=self.other_agent,
            status=ServiceScheduleItem.ItemStatus.CONFIRMED,
        )

        self.client.force_login(self.agent)
        resp = self.client.get(reverse('app_agent_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Alpha Service')
        self.assertNotContains(resp, 'Beta Service')
        self.assertNotContains(resp, 'do not show this')

    def test_customer_limited_view_hides_internal_metadata(self):
        exec_plan = ServiceSchedulePlan.objects.create(
            submission=self.submission,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.ACTIVE,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=3,
            based_on=self.plan,
            created_by=self.admin,
            updated_by=self.admin,
        )
        ServiceScheduleItem.objects.create(
            schedule_plan=exec_plan,
            service_code='svc_alpha',
            service_label='Alpha Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=timezone.now() + timedelta(days=2),
            ends_at=timezone.now() + timedelta(days=2, hours=1),
            duration_minutes=60,
            assigned_agent=self.agent,
            status=ServiceScheduleItem.ItemStatus.CONFIRMED,
            source_reason='internal negotiation reason',
            notes='internal secret notes',
            recommendation_source='agent_finalized',
        )
        UserSettlementPlan.objects.create(user=self.customer, service_schedule={})

        safe = get_schedule_for_display(self.customer)
        self.assertTrue(safe)
        first_date = next(iter(safe.keys()))
        item = safe[first_date][0]
        self.assertNotIn('notes', item)
        self.assertNotIn('location_text', item)
        self.assertNotIn('agent_id', item)
        self.assertNotIn('source_reason', item)
        self.assertNotIn('recommendation_reason', item)

    def test_search_results_obey_permissions(self):
        url = reverse('app_submission_review_schedule_api', kwargs={'submission_id': self.submission.id})

        self.client.force_login(self.admin)
        admin_resp = self.client.get(url, {'view': 'week', 'q': 'Beta'})
        self.assertEqual(admin_resp.status_code, 200)
        labels = [r['service_label'] for r in admin_resp.json()['items']]
        self.assertEqual(labels, ['Beta Service'])

        self.client.force_login(self.customer)
        cust_resp = self.client.get(url, {'view': 'week', 'q': 'Beta'})
        self.assertEqual(cust_resp.status_code, 302)
