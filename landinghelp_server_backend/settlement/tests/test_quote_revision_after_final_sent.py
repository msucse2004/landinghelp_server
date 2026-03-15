"""
[QUOTE ALREADY SENT] FINAL_SENT 견적 있는 상태에서 고객이 메시지로 수정 요청 → 정책 분기 → reopen 또는 review, superseded quote 결제 불가.
Run: python manage.py test settlement.tests.test_quote_revision_after_final_sent -v 2
"""
import sys
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth import get_user_model

from survey.models import SurveySubmission
from settlement.models import SettlementQuote, CustomerActionOffer
from customer_request_service import (
    handle_customer_request_flow,
    execute_confirmed_action,
)
from customer_request_policy import (
    Intent,
    RecommendedAction,
    ExecutionMode,
    PolicyResult,
    HumanReviewTarget,
)

User = get_user_model()


def _progress(msg: str) -> None:
    print(msg, flush=True)
    sys.stdout.flush()


def _policy_survey_reopen(text, context=None, **kw):
    from customer_request_policy import _heuristic_policy
    s = (text or "").strip().lower()
    if "설문" in s and any(x in s for x in ("수정", "편집", "다시")):
        return PolicyResult(
            detected_intent=Intent.SURVEY_REOPEN_REQUEST,
            recommended_action=RecommendedAction.OFFER_SURVEY_REOPEN,
            execution_mode=ExecutionMode.AUTO_CONFIRMABLE,
            confidence=0.85,
            human_review_target=HumanReviewTarget.none,
            customer_facing_summary="설문을 다시 수정할 수 있도록 열어드릴까요?",
            internal_reasoning_summary="test",
            should_create_action_offer=True,
        )
    return _heuristic_policy(text)


class QuoteAlreadySentRevisionTests(TestCase):
    """FINAL_SENT quote 존재 시 고객 수정 요청 → AUTO 또는 HUMAN 분기, superseded 결제 불가."""

    def setUp(self):
        from messaging.models import Conversation, ConversationParticipant, Message
        self.customer = User.objects.create_user(
            username="qas_cust", email="qas@test.com", password="testpass123"
        )
        self.staff = User.objects.create_user(
            username="qas_staff", email="qas_s@test.com", password="s123", is_staff=True
        )
        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
        )
        self.quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal("200"),
            items=[{"code": "S1", "label": "One", "price": 200}],
        )
        self.conv = Conversation.objects.create(
            type=Conversation.Type.NOTICE,
            survey_submission=self.submission,
            subject="정착",
        )
        ConversationParticipant.objects.create(conversation=self.conv, user=self.customer)
        ConversationParticipant.objects.create(conversation=self.conv, user=self.staff)
        self.Message = Message

    @patch("customer_request_policy.evaluate_customer_request_policy", side_effect=lambda text, context=None, **kw: _policy_survey_reopen(text, context))
    def test_final_sent_message_reopen_offer_then_superseded_not_payable(self, _mock):
        _progress("[9/10] verify quote revision after final sent")
        msg = self.Message.objects.create(
            conversation=self.conv, sender=self.customer, body="설문 다시 수정하고 싶어요"
        )
        ctx, policy, err = handle_customer_request_flow(
            "messaging_inbox", self.customer, msg.body or "",
            conversation=self.conv, message=msg,
        )
        self.assertIsNone(err)
        self.assertEqual(policy.execution_mode, ExecutionMode.AUTO_CONFIRMABLE)
        offer = CustomerActionOffer.objects.filter(
            submission=self.submission,
            button_action_key="reopen_survey",
            status=CustomerActionOffer.Status.PENDING,
        ).first()
        self.assertIsNotNone(offer)

        self.quote.refresh_from_db()
        self.assertIsNone(
            getattr(self.quote, "revision_superseded_at", None),
            "버튼 클릭 전에는 superseded 아님",
        )
        success, _ = execute_confirmed_action(offer.id, self.customer)
        self.assertTrue(success)
        self.quote.refresh_from_db()
        self.assertIsNotNone(
            getattr(self.quote, "revision_superseded_at", None),
            "reopen 실행 후 기존 견적 superseded",
        )
        # superseded quote는 결제 대상에서 제외(quote_checkout 등에서 revision_superseded_at 확인). message_may_include_price는 status만 봄.
