"""
[REGRESSION] 기존 기능 유지: survey resume, 가격 비노출, 메시지 발송, 견적 검토 플로우.
Run: python manage.py test settlement.tests.test_workflow_regression -v 2
"""
import sys
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth import get_user_model

from survey.models import SurveySubmission
from settlement.models import SettlementQuote
from settlement.constants import message_may_include_price, can_view_price, quote_for_customer
from customer_request_policy import _heuristic_policy, Intent, ExecutionMode, RecommendedAction

User = get_user_model()


def _progress(msg: str) -> None:
    print(msg, flush=True)
    sys.stdout.flush()


class RegressionSurveyResumeTests(TestCase):
    """기존 survey resume 정책: SURVEY_RESUME_REQUEST, AUTO_CONFIRMABLE."""

    def test_survey_resume_intent_unchanged(self):
        _progress("[REGRESSION] survey resume: intent and execution mode")
        policy = _heuristic_policy("링크 다시 주세요 설문 이어서 하고 싶어요")
        self.assertEqual(policy.detected_intent, Intent.SURVEY_RESUME_REQUEST)
        self.assertEqual(policy.recommended_action, RecommendedAction.OFFER_SURVEY_RESUME)
        self.assertEqual(policy.execution_mode, ExecutionMode.AUTO_CONFIRMABLE)


class RegressionPriceVisibilityTests(TestCase):
    """기존 가격 비노출 정책: DRAFT/NEGOTIATING 에서 가격 노출 안 함."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="reg_cust", email="reg@test.com", password="testpass123"
        )
        self.submission = SurveySubmission.objects.create(
            user=self.user, email=self.user.email, status=SurveySubmission.Status.SUBMITTED
        )

    def test_price_not_exposed_for_draft(self):
        _progress("[REGRESSION] price visibility: draft/negotiating")
        self.assertFalse(message_may_include_price(SettlementQuote.Status.DRAFT))
        self.assertFalse(message_may_include_price(SettlementQuote.Status.NEGOTIATING))
        quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.DRAFT,
            total=Decimal("100"),
            items=[],
        )
        self.assertFalse(can_view_price(self.user, quote))

    def test_quote_for_customer_masks_draft(self):
        quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.DRAFT,
            total=Decimal("200"),
            items=[{"code": "A", "label": "A", "price": 200}],
        )
        out = quote_for_customer(quote)
        self.assertIsNotNone(out)
        self.assertIsNone(out.get("total"))
        for item in out.get("items", []):
            self.assertTrue(item.get("_masked"))


class RegressionMessageSendTests(TestCase):
    """메시지 발송 기본: 대화/메시지 생성 가능."""

    def test_message_model_create(self):
        _progress("[REGRESSION] message send basic")
        from messaging.models import Conversation, ConversationParticipant, Message
        user = User.objects.create_user(username="msg_u", email="msg@test.com", password="p")
        conv = Conversation.objects.create(type=Conversation.Type.NOTICE, subject="Test")
        ConversationParticipant.objects.create(conversation=conv, user=user)
        msg = Message.objects.create(conversation=conv, sender=user, body="Hello")
        self.assertIsNotNone(msg.id)
        self.assertEqual(msg.body, "Hello")


class RegressionQuoteReviewFlowTests(TestCase):
    """견적 검토 플로우 핵심: QuoteChangeRequest 생성, 상태값."""

    def test_quote_change_request_status_values(self):
        _progress("[REGRESSION] quote review flow")
        from settlement.models import QuoteChangeRequest
        self.assertIn(QuoteChangeRequest.Status.OPEN, dir(QuoteChangeRequest.Status))
        self.assertIn(QuoteChangeRequest.Status.ANALYZED, dir(QuoteChangeRequest.Status))
        self.assertIn(QuoteChangeRequest.Status.IN_REVIEW, dir(QuoteChangeRequest.Status))
        self.assertIn(QuoteChangeRequest.Status.CUSTOMER_ACTION_REQUIRED, dir(QuoteChangeRequest.Status))
        self.assertIn(QuoteChangeRequest.Status.APPLIED, dir(QuoteChangeRequest.Status))
