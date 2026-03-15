from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from settlement.availability_request import (
    compute_overlapping_windows,
    create_post_payment_availability_requests,
    submit_availability_response,
)
from settlement.models import (
    AvailabilityRequest,
    ServiceScheduleItem,
    ServiceSchedulePlan,
    SettlementQuote,
    UserSettlementPlan,
)
from settlement.quote_checkout import process_quote_payment
from settlement.scheduling_engine import get_agent_availability_for_submission
from survey.models import SurveySubmission


User = get_user_model()


class InternalAvailabilityWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='avail_admin',
            email='avail_admin@test.com',
            password='pass1234',
            role=User.Role.ADMIN,
            is_staff=True,
        )
        self.supervisor = User.objects.create_user(
            username='avail_supervisor',
            email='avail_supervisor@test.com',
            password='pass1234',
            role=User.Role.SUPERVISOR,
            is_staff=True,
        )
        self.hq_staff = User.objects.create_user(
            username='avail_hq_staff',
            email='avail_hq_staff@test.com',
            password='pass1234',
            role=User.Role.HQ_STAFF,
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='avail_customer',
            email='avail_customer@test.com',
            password='pass1234',
            role=User.Role.CUSTOMER,
        )
        self.agent = User.objects.create_user(
            username='avail_agent',
            email='avail_agent@test.com',
            password='pass1234',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.AWAITING_PAYMENT,
            case_stage=SurveySubmission.CaseStage.QUOTE_SENT,
            requested_required_services=['SVC1'],
            answers={'region': 'North Carolina'},
        )
        self.quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal('1800'),
            items=[{'code': 'SVC1', 'label': 'Service 1', 'price': 1800}],
        )
        self.user_plan = UserSettlementPlan.objects.create(
            user=self.customer,
            assigned_agent=self.agent,
            state='NC',
            city='Charlotte',
            checkout_total=Decimal('1800'),
        )
        self.schedule_plan = ServiceSchedulePlan.objects.create(
            submission=self.submission,
            quote=self.quote,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.DRAFT,
            source=ServiceSchedulePlan.Source.ADMIN,
            version=1,
            created_by=self.admin,
            updated_by=self.admin,
        )
        ServiceScheduleItem.objects.create(
            schedule_plan=self.schedule_plan,
            service_code='SVC1',
            service_label='Service 1',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            duration_minutes=60,
            assigned_agent=self.agent,
            status=ServiceScheduleItem.ItemStatus.SCHEDULED,
        )

    @patch('settlement.scheduling_engine.ensure_submission_schedule_draft', return_value=(None, False))
    def test_payment_completion_creates_internal_availability_requests_for_customer_and_agent(self, _mock_schedule_draft):
        quote, err = process_quote_payment(self.customer, quote_id=self.quote.id)

        self.assertIsNone(err)
        self.assertIsNotNone(quote)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.case_stage, SurveySubmission.CaseStage.PAYMENT_COMPLETED)

        requests = AvailabilityRequest.objects.filter(submission=self.submission)
        self.assertEqual(requests.count(), 2)
        self.assertEqual(
            set(requests.values_list('participant_role', flat=True)),
            {
                AvailabilityRequest.ParticipantRole.CUSTOMER,
                AvailabilityRequest.ParticipantRole.AGENT,
            },
        )
        self.assertTrue(requests.filter(target_user=self.customer).exists())
        self.assertTrue(requests.filter(target_user=self.agent).exists())

    def test_submit_availability_response_and_compute_overlap_across_timezones(self):
        result = create_post_payment_availability_requests(self.submission, actor=self.admin, schedule_plan=self.schedule_plan, notify=False)
        customer_request = result['customer_request']
        agent_request = result['agent_requests'][0]

        customer_response = submit_availability_response(
            customer_request,
            self.customer,
            'America/New_York',
            [
                {'weekday': 0, 'start_time': '09:00', 'end_time': '12:00', 'timezone_name': 'America/New_York'},
                {'weekday': 2, 'start_time': '14:00', 'end_time': '18:00', 'timezone_name': 'America/New_York'},
            ],
        )
        agent_response = submit_availability_response(
            agent_request,
            self.agent,
            'America/Chicago',
            [
                {'weekday': 0, 'start_time': '08:00', 'end_time': '11:00', 'timezone_name': 'America/Chicago'},
                {'weekday': 2, 'start_time': '13:00', 'end_time': '15:00', 'timezone_name': 'America/Chicago'},
            ],
        )

        overlaps = compute_overlapping_windows(
            customer_response,
            agent_response,
            output_timezone='America/New_York',
        )

        self.assertEqual(
            overlaps,
            [
                {'weekday': 0, 'weekday_label': '월요일', 'start_time': '09:00', 'end_time': '12:00', 'timezone_name': 'America/New_York'},
                {'weekday': 2, 'weekday_label': '수요일', 'start_time': '14:00', 'end_time': '16:00', 'timezone_name': 'America/New_York'},
            ],
        )

    def test_internal_availability_form_submission_route(self):
        result = create_post_payment_availability_requests(self.submission, actor=self.admin, schedule_plan=self.schedule_plan, notify=False)
        customer_request = result['customer_request']

        self.client.force_login(self.customer)
        response = self.client.get(reverse('availability_request_input', kwargs={'request_id': customer_request.id}))
        self.assertEqual(response.status_code, 200)

        submit_response = self.client.post(
            reverse('availability_request_submit', kwargs={'request_id': customer_request.id}),
            {
                'timezone_name': 'America/New_York',
                'weekday[]': ['0', '2'],
                'start_time[]': ['09:00', '14:00'],
                'end_time[]': ['12:00', '18:00'],
                'slot_timezone[]': ['America/New_York', 'America/New_York'],
            },
        )
        self.assertEqual(submit_response.status_code, 302)
        customer_request.refresh_from_db()
        self.assertEqual(customer_request.status, AvailabilityRequest.Status.RESPONDED)
        self.assertEqual(customer_request.responses.count(), 1)
        self.assertEqual(customer_request.latest_response().slots.count(), 2)

    def test_schedule_workbench_exposes_availability_to_admin_and_supervisor_only(self):
        result = create_post_payment_availability_requests(self.submission, actor=self.admin, schedule_plan=self.schedule_plan, notify=False)
        customer_request = result['customer_request']
        agent_request = result['agent_requests'][0]
        submit_availability_response(
            customer_request,
            self.customer,
            'America/New_York',
            [{'weekday': 0, 'start_time': '09:00', 'end_time': '12:00', 'timezone_name': 'America/New_York'}],
        )
        submit_availability_response(
            agent_request,
            self.agent,
            'America/New_York',
            [{'weekday': 0, 'start_time': '10:00', 'end_time': '13:00', 'timezone_name': 'America/New_York'}],
        )

        url = reverse('app_submission_review_schedule', kwargs={'submission_id': self.submission.id})

        self.client.force_login(self.admin)
        admin_response = self.client.get(url)
        self.assertEqual(admin_response.status_code, 200)
        self.assertGreaterEqual(len(admin_response.context['availability_request_rows']), 2)
        self.assertEqual(len(admin_response.context['availability_overlap_rows']), 1)
        self.client.logout()

        self.client.force_login(self.supervisor)
        supervisor_response = self.client.get(url)
        self.assertEqual(supervisor_response.status_code, 200)
        self.assertGreaterEqual(len(supervisor_response.context['availability_request_rows']), 2)
        self.client.logout()

        self.client.force_login(self.hq_staff)
        hq_response = self.client.get(url)
        self.assertEqual(hq_response.status_code, 200)
        self.assertEqual(hq_response.context['availability_request_rows'], [])
        self.assertEqual(hq_response.context['availability_overlap_rows'], [])

    def test_internal_availability_slots_are_used_as_schedule_input_windows(self):
        result = create_post_payment_availability_requests(self.submission, actor=self.admin, schedule_plan=self.schedule_plan, notify=False)
        agent_request = result['agent_requests'][0]

        submit_availability_response(
            agent_request,
            self.agent,
            'America/New_York',
            [
                {
                    'weekday': 0,
                    'start_time': '09:00',
                    'end_time': '11:00',
                    'timezone_name': 'America/New_York',
                }
            ],
        )

        windows_by_agent = get_agent_availability_for_submission(self.submission, schedule_plan=self.schedule_plan)
        self.assertIn(self.agent.id, windows_by_agent)
        self.assertTrue(len(windows_by_agent[self.agent.id]) >= 1)
