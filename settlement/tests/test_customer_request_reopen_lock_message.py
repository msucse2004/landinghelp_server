from django.contrib.auth import get_user_model
from django.test import TestCase

from customer_request_policy import ExecutionMode, RecommendedAction
from customer_request_service import RequestContext, analyze_customer_request
from settlement.models import ServiceSchedulePlan, SettlementQuote
from survey.models import SurveySubmission


User = get_user_model()


class SurveyReopenLockMessageTests(TestCase):
    def test_reopen_request_after_quote_release_with_schedule_returns_polite_reply_only(self):
        user = User.objects.create_user(
            username='reopen_lock_user',
            email='reopen_lock_user@test.com',
            password='testpass123',
        )
        submission = SurveySubmission.objects.create(
            user=user,
            email=user.email,
            status=SurveySubmission.Status.AWAITING_PAYMENT,
            answers={},
        )
        SettlementQuote.objects.create(
            submission=submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=100,
            items=[{'code': 'S1', 'label': 'Service 1', 'price': 100}],
        )
        ServiceSchedulePlan.objects.create(
            submission=submission,
            customer=user,
            status=ServiceSchedulePlan.Status.REVIEWING,
            source=ServiceSchedulePlan.Source.ADMIN,
            version=1,
        )

        ctx = RequestContext(
            channel='customer_quote_revision',
            user=user,
            text='설문 다시 수정하고 싶어요',
            conversation=None,
            message=None,
            submission=submission,
            quote=None,
            change_request=None,
            extra={},
        )

        result = analyze_customer_request(ctx)
        policy = result.policy

        self.assertEqual(policy.execution_mode, ExecutionMode.REPLY_ONLY)
        self.assertEqual(policy.recommended_action, RecommendedAction.REPLY_WITH_INFORMATION)
        self.assertFalse(policy.should_create_action_offer)
        self.assertIn('설문을 다시 여는 것이 어려운 점', policy.customer_facing_summary)

    def test_reopen_request_awaiting_payment_with_released_quote_is_blocked_without_schedule(self):
        user = User.objects.create_user(
            username='reopen_lock_user2',
            email='reopen_lock_user2@test.com',
            password='testpass123',
        )
        submission = SurveySubmission.objects.create(
            user=user,
            email=user.email,
            status=SurveySubmission.Status.AWAITING_PAYMENT,
            answers={},
        )
        SettlementQuote.objects.create(
            submission=submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=220,
            items=[{'code': 'S2', 'label': 'Service 2', 'price': 220}],
        )

        ctx = RequestContext(
            channel='messaging_inbox',
            user=user,
            text='서비스 수정하고 싶어요. 설문 다시 열어주세요',
            conversation=None,
            message=None,
            submission=submission,
            quote=None,
            change_request=None,
            extra={},
        )

        result = analyze_customer_request(ctx)
        policy = result.policy

        self.assertEqual(policy.execution_mode, ExecutionMode.REPLY_ONLY)
        self.assertEqual(policy.recommended_action, RecommendedAction.REPLY_WITH_INFORMATION)
        self.assertFalse(policy.should_create_action_offer)
        self.assertIn('설문을 다시 여는 것이 어려운 점', policy.customer_facing_summary)
