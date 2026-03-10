"""
정책 테이블 기반 proposal 생성/확인/거절/피드백 통합 테스트.

테스트 범위:
1. 서비스 변경 메시지 → proposal 생성, 즉시 실행 안 됨
2. proposal confirm → survey reopen action 실행
3. proposal decline → action 실행 안 됨
4. heuristic high confidence → LLM 호출 안 함
5. ambiguous request → ollama/gemini escalation
6. high-risk request → human review 경로
7. 이미 처리된 proposal 재확인 → 중복 실행 방지
8. feedback log(학습 신호) 생성 확인

Run: python manage.py test messaging.tests.test_proposal_flow --verbosity=2
"""
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.contrib.auth import get_user_model

from messaging.models import (
    Conversation,
    ConversationParticipant,
    Message,
    CustomerRequestIntentAnalysis,
    CustomerActionProposal,
    CustomerActionFeedbackLog,
)
from survey.models import SurveySubmission
from settlement.models import SettlementQuote
from customer_request_policy import (
    Intent,
    RecommendedAction,
    ExecutionMode,
    RiskLevel,
    ActionPolicyEntry,
    INTENT_POLICY,
    ACTION_CODE_POLICY,
    get_policy_for_intent,
    get_policy_for_action_code,
    classify_customer_request,
    _heuristic_policy,
    is_high_risk_intent,
    is_low_risk_intent,
)

User = get_user_model()


class _FlowTestMixin:
    """공통 fixture: customer, staff, submission, quote, conversation, message."""

    def _setup_flow(self):
        self.customer = User.objects.create_user(
            username="flow_cust", email="cust@test.com", password="p",
        )
        self.staff = User.objects.create_user(
            username="flow_staff", email="staff@test.com", password="p", is_staff=True,
        )
        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
        )
        self.quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal("300"),
            items=[{"code": "S1", "label": "Service A", "price": 300}],
        )
        self.conv = Conversation.objects.create(
            type=Conversation.Type.APPOINTMENT,
            survey_submission=self.submission,
        )
        ConversationParticipant.objects.create(conversation=self.conv, user=self.customer)
        ConversationParticipant.objects.create(conversation=self.conv, user=self.staff)
        self.msg = Message.objects.create(
            conversation=self.conv, sender=self.customer, body="서비스를 변경하고 싶어요",
        )


# =========================================================================
# 1. 정책 테이블 구조 테스트
# =========================================================================


class PolicyTableStructureTests(TestCase):
    """정책 테이블이 모든 Intent를 포함하고, 인덱스가 올바르게 생성되었는지."""

    def test_every_intent_has_policy_entry(self):
        for intent in Intent:
            entry = get_policy_for_intent(intent)
            self.assertIsNotNone(entry, f"{intent} missing from INTENT_POLICY")
            self.assertEqual(entry.intent, intent)

    def test_low_risk_entries_have_action_code(self):
        for entry in INTENT_POLICY.values():
            if entry.risk_level == RiskLevel.LOW:
                self.assertTrue(
                    bool(entry.action_code),
                    f"LOW risk {entry.intent} missing action_code",
                )
                self.assertTrue(bool(entry.proposal_type))
                self.assertTrue(bool(entry.button_label))
                self.assertTrue(bool(entry.guide_message))
                self.assertTrue(bool(entry.success_message))

    def test_action_code_index_matches(self):
        for code, entry in ACTION_CODE_POLICY.items():
            self.assertEqual(code, entry.action_code)

    def test_risk_level_consistency(self):
        for entry in INTENT_POLICY.values():
            if entry.risk_level == RiskLevel.LOW:
                self.assertTrue(entry.requires_user_confirmation)
                self.assertTrue(entry.allows_direct_execution)
                self.assertFalse(entry.requires_human_review)
                self.assertEqual(entry.execution_mode, ExecutionMode.AUTO_CONFIRMABLE)
            elif entry.risk_level == RiskLevel.HIGH:
                self.assertTrue(entry.requires_human_review)
                self.assertEqual(entry.execution_mode, ExecutionMode.HUMAN_REVIEW_REQUIRED)

    def test_is_high_risk_derived_from_table(self):
        self.assertTrue(is_high_risk_intent(Intent.SCHEDULE_CHANGE_REQUEST))
        self.assertTrue(is_high_risk_intent(Intent.REFUND_REQUEST))
        self.assertTrue(is_high_risk_intent(Intent.LEGAL_COMPLAINT))
        self.assertFalse(is_high_risk_intent(Intent.SURVEY_REOPEN_REQUEST))

    def test_is_low_risk_derived_from_table(self):
        self.assertTrue(is_low_risk_intent(Intent.SURVEY_REOPEN_REQUEST))
        self.assertTrue(is_low_risk_intent(Intent.PAYMENT_LINK_RESEND_REQUEST))
        self.assertFalse(is_low_risk_intent(Intent.SCHEDULE_CHANGE_REQUEST))


# =========================================================================
# 2. 휴리스틱 분류 테스트
# =========================================================================


class HeuristicClassificationTests(TestCase):
    """4. heuristic high confidence → LLM 호출 안 함."""

    def test_service_change_maps_to_survey_reopen(self):
        result = _heuristic_policy("서비스를 변경하고 싶어요")
        self.assertEqual(result.detected_intent, Intent.SURVEY_REOPEN_REQUEST)
        self.assertEqual(result.execution_mode, ExecutionMode.AUTO_CONFIRMABLE)
        self.assertTrue(result.should_create_action_offer)
        self.assertEqual(result.source, "heuristic")
        self.assertGreaterEqual(result.confidence, 0.65)

    def test_survey_edit_heuristic(self):
        result = _heuristic_policy("설문을 수정하고 싶어요")
        self.assertEqual(result.detected_intent, Intent.SURVEY_REOPEN_REQUEST)
        self.assertTrue(result.should_create_action_offer)

    def test_quote_resend_heuristic(self):
        result = _heuristic_policy("견적서를 다시 보내주세요")
        self.assertEqual(result.detected_intent, Intent.QUOTE_RESEND_REQUEST)
        self.assertTrue(result.should_create_action_offer)

    def test_payment_link_resend_heuristic(self):
        result = _heuristic_policy("결제 링크를 다시 보내주세요")
        self.assertEqual(result.detected_intent, Intent.PAYMENT_LINK_RESEND_REQUEST)
        self.assertTrue(result.should_create_action_offer)

    def test_refund_heuristic_high_risk(self):
        result = _heuristic_policy("환불 요청합니다")
        self.assertEqual(result.detected_intent, Intent.REFUND_REQUEST)
        self.assertFalse(result.should_create_action_offer)
        self.assertEqual(result.execution_mode, ExecutionMode.HUMAN_REVIEW_REQUIRED)

    def test_legal_complaint_high_risk(self):
        result = _heuristic_policy("법적 조치를 취하겠습니다")
        self.assertEqual(result.detected_intent, Intent.LEGAL_COMPLAINT)
        self.assertFalse(result.should_create_action_offer)

    def test_schedule_change_high_risk(self):
        """6. high-risk request → human review 경로."""
        result = _heuristic_policy("일정 변경하고 싶어요")
        self.assertEqual(result.detected_intent, Intent.SCHEDULE_CHANGE_REQUEST)
        self.assertEqual(result.execution_mode, ExecutionMode.HUMAN_REVIEW_REQUIRED)
        self.assertFalse(result.should_create_action_offer)

    def test_ambiguous_message_low_confidence(self):
        result = _heuristic_policy("음... 좀 애매한데요")
        self.assertEqual(result.detected_intent, Intent.GENERAL_QUESTION)
        self.assertFalse(result.should_create_action_offer)
        self.assertLess(result.confidence, 0.65)

    @patch("customer_request_llm.call_ollama_classify", side_effect=Exception("skip"))
    @patch("customer_request_llm.call_gemini_classify", side_effect=Exception("skip"))
    def test_high_confidence_heuristic_skips_llm(self, mock_gemini, mock_ollama):
        """4. heuristic confidence 높으면 LLM 호출 안 함."""
        result = classify_customer_request("서비스를 변경하고 싶어요", allow_llm=True)
        self.assertEqual(result.detected_intent, Intent.SURVEY_REOPEN_REQUEST)
        mock_ollama.assert_not_called()
        mock_gemini.assert_not_called()


# =========================================================================
# 3. LLM escalation 테스트
# =========================================================================


class LLMEscalationTests(TestCase):
    """5. ambiguous request → ollama/gemini escalation."""

    @patch("customer_request_llm.call_gemini_classify")
    @patch("customer_request_llm.call_ollama_classify")
    def test_ambiguous_calls_ollama(self, mock_ollama, mock_gemini):
        from customer_request_policy import PolicyResult, HumanReviewTarget

        mock_ollama.return_value = PolicyResult(
            detected_intent=Intent.SURVEY_REOPEN_REQUEST,
            recommended_action=RecommendedAction.OFFER_SURVEY_REOPEN,
            execution_mode=ExecutionMode.AUTO_CONFIRMABLE,
            confidence=0.85,
            human_review_target=HumanReviewTarget.none,
            customer_facing_summary="ok",
            internal_reasoning_summary="ollama",
            should_create_action_offer=True,
            source="ollama",
        )
        result = classify_customer_request("좀 다른 걸로 바꾸고 싶은데요", allow_llm=True)
        mock_ollama.assert_called_once()
        self.assertEqual(result.detected_intent, Intent.SURVEY_REOPEN_REQUEST)
        self.assertEqual(result.source, "ollama")


# =========================================================================
# 4. Proposal 생성 (즉시 실행 안 됨)
# =========================================================================


class ProposalCreationTests(_FlowTestMixin, TestCase):
    """1. '서비스를 변경하고 싶어요' → proposal 생성, 즉시 실행 안 됨."""

    def setUp(self):
        self._setup_flow()

    @patch("customer_request_service.create_customer_auto_reply")
    def test_service_change_creates_proposal_no_execution(self, mock_reply):
        from customer_request_service import handle_customer_request_flow

        result = handle_customer_request_flow(
            "messaging_inbox", self.customer, "서비스를 변경하고 싶어요",
            conversation=self.conv, message=self.msg,
        )
        self.assertIsNotNone(result.proposal)
        self.assertTrue(result.should_require_user_confirmation)
        self.assertFalse(result.should_route_to_human_review)

        proposal = result.proposal
        self.assertEqual(proposal.status, CustomerActionProposal.Status.PROPOSED)
        self.assertEqual(proposal.action_code, "reopen_survey")
        self.assertEqual(proposal.proposal_type, "SURVEY_REOPEN")
        self.assertEqual(proposal.submission_id, self.submission.id)

        self.submission.refresh_from_db()
        self.assertEqual(
            self.submission.status, SurveySubmission.Status.SUBMITTED,
            "submission 상태가 변경되면 안 됨 (즉시 실행 방지)",
        )

    @patch("customer_request_service.create_customer_auto_reply")
    def test_high_risk_routes_to_human_review(self, mock_reply):
        """6. high-risk → human review."""
        from customer_request_service import handle_customer_request_flow

        msg = Message.objects.create(
            conversation=self.conv, sender=self.customer,
            body="일정을 변경하고 싶어요",
        )
        result = handle_customer_request_flow(
            "messaging_inbox", self.customer, "일정을 변경하고 싶어요",
            conversation=self.conv, message=msg,
        )
        self.assertIsNone(result.proposal)
        self.assertTrue(result.should_route_to_human_review)


# =========================================================================
# 5. Proposal Confirm → Action 실행
# =========================================================================


class ProposalConfirmTests(_FlowTestMixin, TestCase):
    """2. proposal confirm → survey reopen action 실행."""

    def setUp(self):
        self._setup_flow()
        self.analysis = CustomerRequestIntentAnalysis.objects.create(
            customer=self.customer,
            conversation=self.conv,
            original_text="서비스를 변경하고 싶어요",
            predicted_intent=Intent.SURVEY_REOPEN_REQUEST.value,
            predicted_action=RecommendedAction.OFFER_SURVEY_REOPEN.value,
            execution_mode=ExecutionMode.AUTO_CONFIRMABLE.value,
            confidence=0.75,
            source="heuristic",
        )
        self.proposal = CustomerActionProposal.objects.create(
            analysis=self.analysis,
            proposal_type="SURVEY_REOPEN",
            title="설문 수정",
            body="설문을 다시 수정할 수 있도록 열어드릴까요?",
            action_code="reopen_survey",
            action_payload={"submission_id": self.submission.id},
            status=CustomerActionProposal.Status.PROPOSED,
            submission=self.submission,
            conversation=self.conv,
        )

    @patch("customer_request_service.create_customer_auto_reply")
    def test_confirm_executes_survey_reopen(self, mock_reply):
        from customer_request_service import confirm_proposal

        success, err, customer_msg = confirm_proposal(self.proposal.id, self.customer)

        self.assertTrue(success, f"confirm failed: {err}")
        self.assertIsNone(err)
        self.assertIsNotNone(customer_msg)

        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, CustomerActionProposal.Status.EXECUTED)
        self.assertIsNotNone(self.proposal.confirmed_at)
        self.assertIsNotNone(self.proposal.executed_at)

        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, SurveySubmission.Status.REVISION_REQUESTED)

    @patch("customer_request_service.create_customer_auto_reply")
    def test_confirm_success_message_from_table(self, mock_reply):
        from customer_request_service import confirm_proposal

        _, _, msg = confirm_proposal(self.proposal.id, self.customer)
        entry = get_policy_for_action_code("reopen_survey")
        self.assertEqual(msg, entry.success_message)


# =========================================================================
# 6. Proposal Decline → Action 실행 안 됨
# =========================================================================


class ProposalDeclineTests(_FlowTestMixin, TestCase):
    """3. proposal decline → action 실행 안 됨."""

    def setUp(self):
        self._setup_flow()
        self.analysis = CustomerRequestIntentAnalysis.objects.create(
            customer=self.customer,
            conversation=self.conv,
            original_text="견적서 다시 보내주세요",
            predicted_intent=Intent.QUOTE_RESEND_REQUEST.value,
            predicted_action=RecommendedAction.OFFER_QUOTE_RESEND.value,
            execution_mode=ExecutionMode.AUTO_CONFIRMABLE.value,
            confidence=0.7,
            source="heuristic",
        )
        self.proposal = CustomerActionProposal.objects.create(
            analysis=self.analysis,
            proposal_type="QUOTE_RESEND",
            title="견적서 재발송",
            body="견적서를 다시 보내드릴까요?",
            action_code="resend_quote",
            action_payload={},
            status=CustomerActionProposal.Status.PROPOSED,
            submission=self.submission,
            conversation=self.conv,
        )

    @patch("customer_request_service.create_customer_auto_reply")
    def test_decline_does_not_execute(self, mock_reply):
        from customer_request_service import decline_proposal

        success, err = decline_proposal(self.proposal.id, self.customer)

        self.assertTrue(success)
        self.assertIsNone(err)

        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, CustomerActionProposal.Status.DECLINED)
        self.assertIsNotNone(self.proposal.declined_at)
        self.assertIsNone(self.proposal.executed_at)


# =========================================================================
# 7. 이미 처리된 proposal 재확인 → 중복 실행 방지
# =========================================================================


class DuplicateConfirmPreventionTests(_FlowTestMixin, TestCase):
    """7. 이미 EXECUTED/DECLINED proposal 재확인 요청 시 중복 실행 방지."""

    def setUp(self):
        self._setup_flow()
        self.analysis = CustomerRequestIntentAnalysis.objects.create(
            customer=self.customer,
            conversation=self.conv,
            original_text="설문 수정하고 싶어요",
            predicted_intent=Intent.SURVEY_REOPEN_REQUEST.value,
            predicted_action=RecommendedAction.OFFER_SURVEY_REOPEN.value,
            execution_mode=ExecutionMode.AUTO_CONFIRMABLE.value,
            confidence=0.75,
            source="heuristic",
        )

    @patch("customer_request_service.create_customer_auto_reply")
    def test_already_executed_returns_success_without_rerun(self, mock_reply):
        from customer_request_service import confirm_proposal
        from django.utils import timezone

        proposal = CustomerActionProposal.objects.create(
            analysis=self.analysis,
            proposal_type="SURVEY_REOPEN",
            action_code="reopen_survey",
            status=CustomerActionProposal.Status.EXECUTED,
            submission=self.submission,
            conversation=self.conv,
            executed_at=timezone.now(),
        )
        success, err, _ = confirm_proposal(proposal.id, self.customer)
        self.assertTrue(success)
        self.assertIsNone(err)

    @patch("customer_request_service.create_customer_auto_reply")
    def test_already_declined_cannot_confirm(self, mock_reply):
        from customer_request_service import confirm_proposal
        from django.utils import timezone

        proposal = CustomerActionProposal.objects.create(
            analysis=self.analysis,
            proposal_type="SURVEY_REOPEN",
            action_code="reopen_survey",
            status=CustomerActionProposal.Status.DECLINED,
            submission=self.submission,
            conversation=self.conv,
            declined_at=timezone.now(),
        )
        success, err, _ = confirm_proposal(proposal.id, self.customer)
        self.assertFalse(success)
        self.assertIn("처리", err)

    @patch("customer_request_service.create_customer_auto_reply")
    def test_already_declined_cannot_decline_again(self, mock_reply):
        from customer_request_service import decline_proposal
        from django.utils import timezone

        proposal = CustomerActionProposal.objects.create(
            analysis=self.analysis,
            proposal_type="SURVEY_REOPEN",
            action_code="reopen_survey",
            status=CustomerActionProposal.Status.DECLINED,
            submission=self.submission,
            conversation=self.conv,
            declined_at=timezone.now(),
        )
        success, err = decline_proposal(proposal.id, self.customer)
        self.assertFalse(success)


# =========================================================================
# 8. Feedback Log 생성 확인
# =========================================================================


class FeedbackLogTests(_FlowTestMixin, TestCase):
    """8. confirm/decline 시 structured learning signal 포함된 feedback log 생성."""

    def setUp(self):
        self._setup_flow()
        self.analysis = CustomerRequestIntentAnalysis.objects.create(
            customer=self.customer,
            conversation=self.conv,
            original_text="서비스를 변경하고 싶어요",
            predicted_intent=Intent.SURVEY_REOPEN_REQUEST.value,
            predicted_action=RecommendedAction.OFFER_SURVEY_REOPEN.value,
            execution_mode=ExecutionMode.AUTO_CONFIRMABLE.value,
            confidence=0.75,
            source="heuristic",
        )
        self.proposal = CustomerActionProposal.objects.create(
            analysis=self.analysis,
            proposal_type="SURVEY_REOPEN",
            title="설문 수정",
            body="설문을 다시 수정할 수 있도록 열어드릴까요?",
            action_code="reopen_survey",
            action_payload={"submission_id": self.submission.id},
            status=CustomerActionProposal.Status.PROPOSED,
            submission=self.submission,
            conversation=self.conv,
        )

    @patch("customer_request_service.create_customer_auto_reply")
    def test_confirm_creates_feedback_logs_with_signal(self, mock_reply):
        from customer_request_service import confirm_proposal

        confirm_proposal(self.proposal.id, self.customer)

        logs = list(
            CustomerActionFeedbackLog.objects
            .filter(proposal=self.proposal)
            .order_by("created_at")
            .values_list("event_type", flat=True)
        )
        self.assertIn("USER_CONFIRMED", logs)
        self.assertIn("ACTION_STARTED", logs)
        self.assertIn("ACTION_SUCCEEDED", logs)

        confirmed_log = CustomerActionFeedbackLog.objects.get(
            proposal=self.proposal, event_type="USER_CONFIRMED",
        )
        payload = confirmed_log.event_payload
        self.assertEqual(payload["user_feedback"], "confirmed")
        self.assertEqual(payload["predicted_intent"], Intent.SURVEY_REOPEN_REQUEST.value)
        self.assertEqual(payload["action_code"], "reopen_survey")

        success_log = CustomerActionFeedbackLog.objects.get(
            proposal=self.proposal, event_type="ACTION_SUCCEEDED",
        )
        self.assertEqual(success_log.event_payload["final_outcome"], "success")

    @patch("customer_request_service.create_customer_auto_reply")
    def test_decline_creates_feedback_log_with_signal(self, mock_reply):
        from customer_request_service import decline_proposal

        decline_proposal(self.proposal.id, self.customer)

        log = CustomerActionFeedbackLog.objects.get(
            proposal=self.proposal, event_type="USER_DECLINED",
        )
        self.assertEqual(log.event_payload["user_feedback"], "declined")
        self.assertEqual(log.event_payload["predicted_intent"], Intent.SURVEY_REOPEN_REQUEST.value)


# =========================================================================
# 9. Correction 감지 테스트
# =========================================================================


class CorrectionDetectionTests(_FlowTestMixin, TestCase):
    """correction 패턴 감지 + USER_CORRECTED 로그."""

    def setUp(self):
        self._setup_flow()
        self.analysis = CustomerRequestIntentAnalysis.objects.create(
            customer=self.customer,
            conversation=self.conv,
            original_text="서비스를 변경하고 싶어요",
            predicted_intent=Intent.SURVEY_REOPEN_REQUEST.value,
            predicted_action=RecommendedAction.OFFER_SURVEY_REOPEN.value,
            execution_mode=ExecutionMode.AUTO_CONFIRMABLE.value,
            confidence=0.75,
            source="heuristic",
        )
        self.proposal = CustomerActionProposal.objects.create(
            analysis=self.analysis,
            proposal_type="SURVEY_REOPEN",
            action_code="reopen_survey",
            status=CustomerActionProposal.Status.EXECUTED,
            submission=self.submission,
            conversation=self.conv,
        )

    def test_correction_detected(self):
        from customer_request_service import detect_and_record_correction

        result = detect_and_record_correction(
            self.conv, "아니요, 일정 변경이었어요", self.customer,
        )
        self.assertIsNotNone(result)
        log = CustomerActionFeedbackLog.objects.get(
            proposal=self.proposal, event_type="USER_CORRECTED",
        )
        self.assertEqual(log.event_payload["user_feedback"], "corrected")
        self.assertIn("일정 변경", log.event_payload["followup_text"])

    def test_no_correction_for_normal_message(self):
        from customer_request_service import detect_and_record_correction

        result = detect_and_record_correction(
            self.conv, "감사합니다", self.customer,
        )
        self.assertIsNone(result)

    def test_correction_not_duplicated(self):
        from customer_request_service import detect_and_record_correction

        detect_and_record_correction(self.conv, "그게 아니라 다른 거요", self.customer)
        detect_and_record_correction(self.conv, "아니요 그게 아니에요", self.customer)
        count = CustomerActionFeedbackLog.objects.filter(
            proposal=self.proposal, event_type="USER_CORRECTED",
        ).count()
        self.assertEqual(count, 1, "동일 proposal에 correction은 1회만 기록")


# =========================================================================
# 10. 정책 테이블 → 서비스 레이어 통합 테스트
# =========================================================================


class PolicyTableServiceIntegrationTests(TestCase):
    """정책 테이블 값이 서비스 레이어 함수에 올바르게 전달되는지."""

    def test_button_label_from_table(self):
        from customer_request_service import _default_button_label_for_code

        for code, entry in ACTION_CODE_POLICY.items():
            self.assertEqual(
                _default_button_label_for_code(code),
                entry.button_label,
                f"button_label mismatch for {code}",
            )

    def test_guide_message_from_table(self):
        from customer_request_service import _proposal_guide_message

        for code, entry in ACTION_CODE_POLICY.items():
            self.assertEqual(
                _proposal_guide_message(code),
                entry.guide_message,
                f"guide_message mismatch for {code}",
            )

    def test_success_message_from_table(self):
        from customer_request_service import _confirm_success_message

        for code, entry in ACTION_CODE_POLICY.items():
            self.assertEqual(
                _confirm_success_message(code),
                entry.success_message,
                f"success_message mismatch for {code}",
            )

    def test_unknown_action_code_falls_back(self):
        from customer_request_service import (
            _default_button_label_for_code,
            _proposal_guide_message,
            _confirm_success_message,
        )

        self.assertEqual(_default_button_label_for_code("nonexistent"), "진행하기")
        self.assertEqual(_proposal_guide_message("nonexistent"), "")
        self.assertEqual(_confirm_success_message("nonexistent"), "요청이 처리되었습니다.")

    def test_action_executors_covers_all_low_risk(self):
        from customer_request_service import _get_action_executors

        executors = _get_action_executors()
        for entry in INTENT_POLICY.values():
            if entry.risk_level == RiskLevel.LOW and entry.action_code:
                self.assertIn(
                    entry.action_code,
                    executors,
                    f"executor missing for LOW risk action_code={entry.action_code}",
                )
