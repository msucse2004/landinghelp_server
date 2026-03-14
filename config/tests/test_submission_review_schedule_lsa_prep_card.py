from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import AgentRating
from settlement.models import SettlementQuote
from settlement.models import SettlementService
from survey.models import SurveySubmission


User = get_user_model()


class SubmissionReviewScheduleLsaPrepCardTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_schedule_lsa_card',
            email='admin_schedule_lsa_card@test.com',
            password='adminpass123',
            role=User.Role.ADMIN,
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='customer_schedule_lsa_card',
            email='customer_schedule_lsa_card@test.com',
            password='custpass123',
            role=User.Role.CUSTOMER,
        )
        self.agent = User.objects.create_user(
            username='agent_schedule_lsa_card',
            email='agent_schedule_lsa_card@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )
        self.other_agent = User.objects.create_user(
            username='agent_schedule_lsa_card_other',
            email='agent_schedule_lsa_card_other@test.com',
            password='agentpass123',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )

    def _review_url(self, submission_id):
        return reverse('app_submission_review', kwargs={'submission_id': submission_id})

    def test_shows_post_payment_schedule_lsa_prep_card_for_agent_direct_services(self):
        in_person_service = SettlementService.objects.create(
            code='svc_in_person',
            name='In-person support',
            category=SettlementService.Category.ADMIN,
            required_time=60,
            customer_price=120,
            agent_price=80,
            is_active=True,
        )
        self.agent.agent_services = [in_person_service.id]
        self.agent.agent_states = ['NC']
        self.agent.save(update_fields=['agent_services', 'agent_states'])
        AgentRating.objects.create(rater=self.customer, agent=self.agent, score=5)

        self.other_agent.agent_services = []
        self.other_agent.agent_states = ['CA']
        self.other_agent.save(update_fields=['agent_services', 'agent_states'])
        AgentRating.objects.create(rater=User.objects.create_user(
            username='another_customer_for_rating',
            email='another_customer_for_rating@test.com',
            password='custpass123',
            role=User.Role.CUSTOMER,
        ), agent=self.other_agent, score=2)

        submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            requested_required_services=['svc_in_person'],
            answers={
                'region': 'North Carolina',
                'service_delivery_per_service': {
                    'svc_in_person': 'agent_direct',
                }
            },
        )
        SettlementQuote.objects.create(
            submission=submission,
            status=SettlementQuote.Status.PAID,
            items=[{'code': 'svc_in_person', 'label': 'In-person support', 'price': 120}],
            total=120,
        )

        self.client.force_login(self.admin)
        response = self.client.get(self._review_url(submission.id))

        self.assertEqual(response.status_code, 200)
        prep = response.context['schedule_lsa_prep']
        self.assertTrue(prep['can_prepare'])
        self.assertTrue(prep['has_paid_quote'])
        self.assertTrue(prep['has_agent_direct_services'])
        self.assertGreaterEqual(len(prep['candidate_agents']), 1)
        self.assertEqual(prep['candidate_agents'][0]['id'], self.agent.id)
        self.assertGreaterEqual(prep['candidate_agents'][0]['service_match_count'], 1)
        self.assertTrue(prep['candidate_agents'][0]['region_match'])
        self.assertNotIn(self.other_agent.id, [row['id'] for row in prep['candidate_agents']])
        self.assertContains(response, reverse('app_submission_review_schedule', kwargs={'submission_id': submission.id}))

    def test_hides_post_payment_schedule_lsa_prep_card_without_agent_direct_services(self):
        submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            requested_required_services=['svc_ai_support'],
            answers={
                'service_delivery_per_service': {
                    'svc_ai_support': 'ai_service',
                }
            },
        )
        SettlementQuote.objects.create(
            submission=submission,
            status=SettlementQuote.Status.PAID,
            items=[{'code': 'svc_ai_support', 'label': 'AI support', 'price': 80}],
            total=80,
        )

        self.client.force_login(self.admin)
        response = self.client.get(self._review_url(submission.id))

        self.assertEqual(response.status_code, 200)
        prep = response.context['schedule_lsa_prep']
        self.assertFalse(prep['can_prepare'])
        self.assertTrue(prep['has_paid_quote'])
        self.assertFalse(prep['has_agent_direct_services'])
        self.assertNotContains(response, '일정 편집 열기 (추천 카드 Drag & Drop)')

    def test_marks_no_agents_when_no_same_state_candidates(self):
        in_person_service = SettlementService.objects.create(
            code='svc_in_person_no_state_match',
            name='In-person support no state match',
            category=SettlementService.Category.ADMIN,
            required_time=60,
            customer_price=120,
            agent_price=80,
            is_active=True,
        )
        self.agent.agent_services = [in_person_service.id]
        self.agent.agent_states = ['CA']
        self.agent.save(update_fields=['agent_services', 'agent_states'])

        submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            requested_required_services=['svc_in_person_no_state_match'],
            answers={
                'region': 'North Carolina',
                'service_delivery_per_service': {
                    'svc_in_person_no_state_match': 'agent_direct',
                }
            },
        )
        SettlementQuote.objects.create(
            submission=submission,
            status=SettlementQuote.Status.PAID,
            items=[{'code': 'svc_in_person_no_state_match', 'label': 'In-person support no state match', 'price': 120}],
            total=120,
        )

        self.client.force_login(self.admin)
        response = self.client.get(self._review_url(submission.id))

        self.assertEqual(response.status_code, 200)
        prep = response.context['schedule_lsa_prep']
        self.assertTrue(prep['can_prepare'])
        self.assertEqual(prep['region_code'], 'NC')
        self.assertEqual(prep['candidate_agents'], [])
        self.assertTrue(prep['same_state_agent_missing'])
        self.assertContains(response, '동일 주(State)에 해당하는 Agent가 없습니다.')
