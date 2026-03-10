"""
고객 요청 정책 엔진 검증: Intent, ExecutionMode, 휴리스틱/LLM 분류.
Run: python manage.py test settlement.tests.test_customer_request_policy -v 2
"""
import sys
from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth import get_user_model

from customer_request_policy import (
    Intent,
    RecommendedAction,
    ExecutionMode,
    HumanReviewTarget,
    PolicyResult,
    evaluate_customer_request_policy,
    _heuristic_policy,
)

User = get_user_model()


def _progress(msg: str) -> None:
    print(msg, flush=True)
    sys.stdout.flush()


class PolicyHeuristicTests(TestCase):
    """휴리스틱 fallback: 설문 재개, 견적 재발송, agent/일정/가격 → HUMAN_REVIEW."""

    def test_survey_reopen_intent_auto_confirmable(self):
        _progress("[1/10] policy: survey reopen → SURVEY_REOPEN_REQUEST / AUTO_CONFIRMABLE")
        policy = _heuristic_policy("설문 다시 수정하고 싶어요")
        self.assertEqual(policy.detected_intent, Intent.SURVEY_REOPEN_REQUEST)
        self.assertEqual(policy.recommended_action, RecommendedAction.OFFER_SURVEY_REOPEN)
        self.assertEqual(policy.execution_mode, ExecutionMode.AUTO_CONFIRMABLE)
        self.assertTrue(policy.should_create_action_offer)

    def test_quote_resend_intent_auto_confirmable(self):
        _progress("[2/10] policy: quote resend → QUOTE_RESEND_REQUEST / AUTO_CONFIRMABLE")
        policy = _heuristic_policy("견적서 다시 보내주세요")
        self.assertEqual(policy.detected_intent, Intent.QUOTE_RESEND_REQUEST)
        self.assertEqual(policy.recommended_action, RecommendedAction.OFFER_QUOTE_RESEND)
        self.assertEqual(policy.execution_mode, ExecutionMode.AUTO_CONFIRMABLE)
        self.assertTrue(policy.should_create_action_offer)

    def test_agent_change_human_review(self):
        _progress("[3/10] policy: agent change → HUMAN_REVIEW_REQUIRED")
        policy = _heuristic_policy("agent 변경 부탁해요")
        self.assertEqual(policy.execution_mode, ExecutionMode.HUMAN_REVIEW_REQUIRED)
        self.assertFalse(policy.should_create_action_offer)

    def test_schedule_change_human_review(self):
        policy = _heuristic_policy("일정 변경 부탁드려요")
        self.assertEqual(policy.execution_mode, ExecutionMode.HUMAN_REVIEW_REQUIRED)

    def test_empty_message_reply_only(self):
        policy = _heuristic_policy("")
        self.assertEqual(policy.execution_mode, ExecutionMode.REPLY_ONLY)


class PolicyEvaluateWithHeuristicTests(TestCase):
    """evaluate_customer_request_policy(allow_llm=False) → 휴리스틱만."""

    def test_evaluate_survey_reopen_without_llm(self):
        _progress("[4/10] evaluate_customer_request_policy (no LLM): survey reopen")
        policy = evaluate_customer_request_policy(
            "설문을 수정하고 싶습니다.",
            context={},
            allow_llm=False,
        )
        self.assertEqual(policy.detected_intent, Intent.SURVEY_REOPEN_REQUEST)
        self.assertEqual(policy.execution_mode, ExecutionMode.AUTO_CONFIRMABLE)
        self.assertTrue(policy.should_create_action_offer)
