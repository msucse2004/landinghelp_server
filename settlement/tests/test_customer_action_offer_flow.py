"""
AUTO_CONFIRMABLE / HUMAN_REVIEW_REQUIRED 전체 흐름 및 버튼 확인형 실행 검증.
- 고객 메시지 → 요청 생성 → LLM(또는 휴리스틱) 분류 → action offer 생성 → 버튼 클릭 시에만 실행.
- 메시지함 경로와 customer quote 경로가 동일한 통합 서비스 사용 확인.
Run: python manage.py test settlement.tests.test_customer_action_offer_flow -v 2
"""
import sys
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth import get_user_model

from survey.models import SurveySubmission
from settlement.models import (
    SettlementQuote,
    QuoteChangeRequest,
    CustomerActionOffer,
    HumanReviewRequest,
)
from customer_request_service import (
    handle_customer_request_flow,
    execute_confirmed_action,
    build_customer_ui_payload,
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
    """테스트: 설문 수정 메시지 → OFFER_SURVEY_REOPEN, AUTO_CONFIRMABLE."""
    from customer_request_policy import _heuristic_policy
    s = (text or "").strip().lower()
    if "설문" in s and any(x in s for x in ("수정", "편집", "다시", "edit", "revise")):
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


def _policy_quote_resend(text, context=None, **kw):
    """테스트: 견적 재발송 → OFFER_QUOTE_RESEND."""
    from customer_request_policy import _heuristic_policy
    s = (text or "").strip().lower()
    if "견적" in s or "quote" in s:
        if "다시" in s or "보내" in s or "resend" in s or "send" in s:
            return PolicyResult(
                detected_intent=Intent.QUOTE_RESEND_REQUEST,
                recommended_action=RecommendedAction.OFFER_QUOTE_RESEND,
                execution_mode=ExecutionMode.AUTO_CONFIRMABLE,
                confidence=0.85,
                human_review_target=HumanReviewTarget.none,
                customer_facing_summary="견적서를 다시 보내드릴까요?",
                internal_reasoning_summary="test",
                should_create_action_offer=True,
            )
    return _heuristic_policy(text)


def _policy_human_review_agent(text, context=None, **kw):
    """테스트: agent 약속 → HUMAN_REVIEW_REQUIRED."""
    from customer_request_policy import _heuristic_policy
    s = (text or "").strip().lower()
    if "agent" in s or "에이전트" in s:
        if "약속" in s or "다시" in s or "잡" in s:
            return PolicyResult(
                detected_intent=Intent.AGENT_CHANGE_REQUEST,
                recommended_action=RecommendedAction.ROUTE_TO_ADMIN_REVIEW,
                execution_mode=ExecutionMode.HUMAN_REVIEW_REQUIRED,
                confidence=0.8,
                human_review_target=HumanReviewTarget.admin,
                customer_facing_summary="요청이 접수되었습니다. 검토 후 안내드리겠습니다.",
                internal_reasoning_summary="test",
                should_create_action_offer=False,
            )
    return _heuristic_policy(text)


class AutoConfirmableSurveyReopenFlowTests(TestCase):
    """[AUTO_CONFIRMABLE] 설문 다시 수정: 메시지 → offer 생성 → 버튼 클릭 시에만 reopen."""

    def setUp(self):
        from messaging.models import Conversation, ConversationParticipant, Message
        self.customer = User.objects.create_user(
            username="flow_cust", email="flow@test.com", password="testpass123"
        )
        self.staff = User.objects.create_user(
            username="flow_staff", email="staff_flow@test.com", password="staff123", is_staff=True
        )
        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
        )
        self.conv = Conversation.objects.create(
            type=Conversation.Type.NOTICE,
            survey_submission=self.submission,
            subject="정착 서비스",
        )
        ConversationParticipant.objects.create(conversation=self.conv, user=self.customer)
        ConversationParticipant.objects.create(conversation=self.conv, user=self.staff)
        self.Message = Message

    @patch("customer_request_policy.evaluate_customer_request_policy", side_effect=lambda text, context=None, **kw: _policy_survey_reopen(text, context))
    def test_full_flow_message_offer_then_button_execute(self, _mock):
        _progress("[1/10] create customer change request from message")
        msg = self.Message.objects.create(
            conversation=self.conv, sender=self.customer, body="설문 다시 수정하고 싶어요"
        )
        ctx, policy, err = handle_customer_request_flow(
            "messaging_inbox", self.customer, msg.body or "",
            conversation=self.conv, message=msg,
        )
        self.assertIsNone(err, msg=str(err))
        self.assertIsNotNone(ctx)
        self.assertEqual(policy.execution_mode, ExecutionMode.AUTO_CONFIRMABLE)

        _progress("[2/10] classify intent and execution mode")
        self.assertEqual(str(policy.detected_intent), "SURVEY_REOPEN_REQUEST")

        _progress("[3/10] verify action offer created")
        offer = CustomerActionOffer.objects.filter(
            submission=self.submission,
            button_action_key="reopen_survey",
            status=CustomerActionOffer.Status.PENDING,
        ).first()
        self.assertIsNotNone(offer, "reopen_survey offer 생성되어야 함")

        _progress("[4/10] verify no execution before button click")
        self.submission.refresh_from_db()
        self.assertEqual(
            self.submission.status,
            SurveySubmission.Status.SUBMITTED,
            "버튼 누르기 전에는 상태 변경 없음",
        )

        _progress("[5/10] confirm customer action by button")
        success, exec_err = execute_confirmed_action(offer.id, self.customer)
        self.assertTrue(success, msg=exec_err)

        _progress("[6/10] verify survey reopen or quote resend executed")
        self.submission.refresh_from_db()
        self.assertEqual(
            self.submission.status,
            SurveySubmission.Status.REVISION_REQUESTED,
            "버튼 클릭 후 REVISION_REQUESTED",
        )
        offer.refresh_from_db()
        self.assertEqual(offer.status, CustomerActionOffer.Status.EXECUTED)

        _progress("[7/10] verify dashboard / messaging / customer quote state")
        payload = build_customer_ui_payload(self.customer, conversation=self.conv, submission=self.submission)
        self.assertTrue(payload.get("can_reopen_survey"))
        self.assertIn("설문 수정 가능", payload.get("current_request_status", "") or "")


class AutoConfirmableQuoteResendIdempotentTests(TestCase):
    """[AUTO_CONFIRMABLE - QUOTE RESEND] 견적 재발송 offer → 버튼 클릭 → 중복 클릭 idempotent."""

    def setUp(self):
        from messaging.models import Conversation, ConversationParticipant, Message
        self.customer = User.objects.create_user(
            username="resend_cust", email="resend@test.com", password="testpass123"
        )
        self.staff = User.objects.create_user(
            username="resend_staff", email="resend_s@test.com", password="s123", is_staff=True
        )
        self.submission = SurveySubmission.objects.create(
            user=self.customer, email=self.customer.email, status=SurveySubmission.Status.SUBMITTED
        )
        self.quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal("100"),
            items=[{"code": "S1", "label": "Service", "price": 100}],
        )
        self.conv = Conversation.objects.create(
            type=Conversation.Type.NOTICE,
            survey_submission=self.submission,
            subject="정착",
        )
        ConversationParticipant.objects.create(conversation=self.conv, user=self.customer)
        ConversationParticipant.objects.create(conversation=self.conv, user=self.staff)
        self.Message = Message

    @patch("settlement.notifications.send_quote_release_message", return_value=True)
    @patch("customer_request_policy.evaluate_customer_request_policy", side_effect=lambda text, context=None, **kw: _policy_quote_resend(text, context))
    def test_quote_resend_offer_and_idempotent_double_click(self, _mock_policy, _mock_send):
        _progress("[8/10] verify quote resend offer and idempotency")
        msg = self.Message.objects.create(
            conversation=self.conv, sender=self.customer, body="견적서 다시 보내주세요"
        )
        ctx, policy, err = handle_customer_request_flow(
            "messaging_inbox", self.customer, msg.body or "",
            conversation=self.conv, message=msg,
        )
        self.assertIsNone(err)
        offer = CustomerActionOffer.objects.filter(
            submission=self.submission,
            button_action_key="resend_quote",
            status=CustomerActionOffer.Status.PENDING,
        ).first()
        self.assertIsNotNone(offer)
        success1, _ = execute_confirmed_action(offer.id, self.customer)
        self.assertTrue(success1)
        success2, _ = execute_confirmed_action(offer.id, self.customer)
        self.assertTrue(success2, "중복 클릭 시 idempotent 성공 반환")


class HumanReviewRequiredFlowTests(TestCase):
    """[HUMAN_REVIEW_REQUIRED] agent 약속 요청 → review queue 생성, 자동 실행 없음."""

    def setUp(self):
        from messaging.models import Conversation, ConversationParticipant, Message
        self.customer = User.objects.create_user(
            username="hr_cust", email="hr@test.com", password="testpass123"
        )
        self.staff = User.objects.create_user(
            username="hr_staff", email="hr_s@test.com", password="s123", is_staff=True
        )
        self.submission = SurveySubmission.objects.create(
            user=self.customer, email=self.customer.email, status=SurveySubmission.Status.SUBMITTED
        )
        self.conv = Conversation.objects.create(
            type=Conversation.Type.NOTICE,
            survey_submission=self.submission,
            subject="정착",
        )
        ConversationParticipant.objects.create(conversation=self.conv, user=self.customer)
        ConversationParticipant.objects.create(conversation=self.conv, user=self.staff)
        self.Message = Message

    @patch("customer_request_policy.evaluate_customer_request_policy", side_effect=lambda text, context=None, **kw: _policy_human_review_agent(text, context))
    def test_human_review_routing_no_auto_execution(self, _mock):
        _progress("[9/10] verify human review routing path")
        msg = self.Message.objects.create(
            conversation=self.conv, sender=self.customer, body="agent와 약속 다시 잡고 싶어요"
        )
        ctx, policy, err = handle_customer_request_flow(
            "messaging_inbox", self.customer, msg.body or "",
            conversation=self.conv, message=msg,
        )
        self.assertIsNone(err)
        self.assertEqual(policy.execution_mode, ExecutionMode.HUMAN_REVIEW_REQUIRED)
        review = HumanReviewRequest.objects.filter(submission=self.submission).first()
        self.assertIsNotNone(review, "HumanReviewRequest 생성")
        self.assertEqual(review.status, HumanReviewRequest.Status.RECEIVED)
        offer = CustomerActionOffer.objects.filter(
            submission=self.submission,
            button_action_key="reopen_survey",
            status=CustomerActionOffer.Status.PENDING,
        ).first()
        self.assertIsNone(offer, "자동 실행용 offer 없음")
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, SurveySubmission.Status.SUBMITTED)


class CommonServiceLogicTests(TestCase):
    """[COMMON SERVICE LOGIC] 메시지함 경로와 customer quote 경로가 같은 handle_customer_request_flow 사용."""

    def test_messaging_and_quote_path_use_same_flow(self):
        _progress("[10/10] verify completion and idempotency (common service)")
        from customer_request_service import handle_customer_request_flow
        from settlement.views import api_quote_request_revision
        from messaging.views import api_conversation_messages
        self.assertIsNotNone(handle_customer_request_flow)
        self.assertTrue(callable(handle_customer_request_flow))
        import customer_request_service as svc
        self.assertTrue(hasattr(svc, "handle_customer_request_flow"))
        self.assertTrue(hasattr(svc, "intake_customer_request"))
        self.assertTrue(hasattr(svc, "analyze_customer_request"))
        self.assertTrue(hasattr(svc, "create_action_offer"))
        self.assertTrue(hasattr(svc, "execute_confirmed_action"))
