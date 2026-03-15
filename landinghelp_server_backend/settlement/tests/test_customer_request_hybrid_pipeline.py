from unittest.mock import patch

from django.test import TestCase

from customer_request_policy import (
    ExecutionMode,
    HumanReviewTarget,
    Intent,
    PolicyResult,
    RecommendedAction,
    classify_customer_request,
)


class HybridPipelineBehaviorTests(TestCase):
    def test_semantic_understands_flight_schedule_typos(self):
        messages = [
            "비행 스캐쥴이 바뀌었어요",
            "비행 스캐줄이 바꼈어요",
            "비행기 도착 시간이 변경됐어요",
        ]
        for message in messages:
            result = classify_customer_request(
                message,
                context={"has_survey_submission": True},
                allow_llm=False,
            )
            self.assertEqual(result.policy.detected_intent, Intent.SURVEY_REOPEN_REQUEST)

    def test_post_submission_airport_pickup_addition_maps_to_survey_reopen(self):
        message = "생각해보니 공항 픽업도 필요해서 연락드립니다"

        submitted_result = classify_customer_request(
            message,
            context={"has_survey_submission": True},
            allow_llm=False,
        )
        self.assertEqual(submitted_result.policy.detected_intent, Intent.SURVEY_REOPEN_REQUEST)

        no_submission_result = classify_customer_request(
            message,
            context={"has_survey_submission": False},
            allow_llm=False,
        )
        self.assertEqual(no_submission_result.policy.detected_intent, Intent.GENERAL_QUESTION)

    @patch("customer_request_policy._local_classifier_policy", return_value=None)
    @patch("customer_request_policy._semantic_policy")
    def test_safety_gate_rejects_low_confidence_semantic(self, mock_semantic, _mock_local):
        mock_semantic.return_value = PolicyResult(
            detected_intent=Intent.SURVEY_REOPEN_REQUEST,
            recommended_action=RecommendedAction.OFFER_SURVEY_REOPEN,
            execution_mode=ExecutionMode.AUTO_CONFIRMABLE,
            confidence=0.58,
            human_review_target=HumanReviewTarget.none,
            customer_facing_summary="설문을 다시 수정할 수 있도록 열어드릴까요?",
            internal_reasoning_summary="mock low confidence semantic",
            should_create_action_offer=True,
            source="semantic",
        )

        result = classify_customer_request("안녕하세요", context={}, allow_llm=False)
        self.assertEqual(result.policy.detected_intent, Intent.GENERAL_QUESTION)
        self.assertEqual(result.policy.source, "heuristic")

    @patch("customer_request_policy._local_classifier_policy")
    @patch("customer_request_policy._semantic_policy")
    def test_local_classifier_runs_after_semantic_safety_gate(self, mock_semantic, mock_local):
        mock_semantic.return_value = PolicyResult(
            detected_intent=Intent.SURVEY_REOPEN_REQUEST,
            recommended_action=RecommendedAction.OFFER_SURVEY_REOPEN,
            execution_mode=ExecutionMode.AUTO_CONFIRMABLE,
            confidence=0.55,
            human_review_target=HumanReviewTarget.none,
            customer_facing_summary="설문을 다시 수정할 수 있도록 열어드릴까요?",
            internal_reasoning_summary="mock low confidence semantic",
            should_create_action_offer=True,
            source="semantic",
        )
        mock_local.return_value = PolicyResult(
            detected_intent=Intent.SURVEY_REOPEN_REQUEST,
            recommended_action=RecommendedAction.OFFER_SURVEY_REOPEN,
            execution_mode=ExecutionMode.AUTO_CONFIRMABLE,
            confidence=0.82,
            human_review_target=HumanReviewTarget.none,
            customer_facing_summary="설문을 다시 수정할 수 있도록 열어드릴까요?",
            internal_reasoning_summary="mock high confidence local classifier",
            should_create_action_offer=True,
            source="local_classifier",
        )

        result = classify_customer_request(
            "도착 시간 다시 바꿔야 해요",
            context={"has_survey_submission": True},
            allow_llm=False,
        )
        self.assertEqual(result.policy.detected_intent, Intent.SURVEY_REOPEN_REQUEST)
        self.assertEqual(result.policy.source, "local_classifier_safe")
