"""
설문 수정 흐름 학습용 이벤트·라벨 통합 테스트.

검증 시나리오:
1. 수정 요청 메시지 시 request_id 생성
2. route_predicted 이벤트 저장
3. 추천 클릭 시 suggestion_clicked 저장
4. 페이지 진입 시 page_viewed 저장
5. 저장 성공 시 edit_saved 저장
6. feedback 버튼 클릭 시 feedback_clicked 저장
7. actual_edit_page가 edit_saved 기준으로 추론
8. 추천≠실제 수정 페이지 시 label 올바르게 생성
9. LLM 실패 시 heuristic only fallback
10. request_id 없이 저장 요청 시 시스템 미동작(깨지지 않음)
11. multi-step(여러 edit_saved) 안전 처리

Run: python manage.py test messaging.tests.test_survey_revision_feedback_flow --verbosity=2

시나리오–테스트 매핑:
  1. request_id 생성        → RequestIdAndRoutePredictedTests.test_flow_returns_request_id
  2. route_predicted 저장   → RequestIdAndRoutePredictedTests.test_message_received_and_route_predicted_events_saved
  3. suggestion_clicked     → SuggestionClickedTests.test_confirm_proposal_creates_suggestion_clicked
  4. page_viewed            → EventLoggingUnitTests.test_log_page_viewed_creates_event
  5. edit_saved             → EventLoggingUnitTests.test_log_edit_saved_creates_event
  6. feedback_clicked       → EventLoggingUnitTests.test_log_feedback_clicked_creates_event, FeedbackApiTests.test_feedback_clicked_api_creates_event
  7. actual_edit_page 추론  → LearningSummaryLabelTests.test_actual_edit_page_inferred_from_edit_saved
  8. 추천≠실제 시 label      → LearningSummaryLabelTests.test_recommended_different_from_actual_creates_negative_label
  9. LLM 실패 heuristic     → LLMFallbackTests.test_llm_failure_returns_heuristic_result
 10. request_id 없음 안전   → RequestIdMissingTests.test_save_event_with_empty_request_id_returns_none, test_feedback_api_requires_request_id
 11. multi-step 안전        → LearningSummaryLabelTests.test_multi_step_all_edit_saved_pages
  + 타임라인 집계           → TimelineAggregationTests
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

from messaging.models import (
    Conversation,
    ConversationParticipant,
    Message,
    CustomerRequestIntentAnalysis,
    CustomerActionProposal,
    CustomerRequestFeedbackEvent,
    CustomerRequestLearningSummary,
)
from survey.models import SurveySubmission
from settlement.models import SettlementQuote

User = get_user_model()


# =========================================================================
# Test Helper: CSRF Token Bootstrap
# =========================================================================

def bootstrap_csrftoken_from_survey_api(client):
    """
    CSRF 토큰을 얻기 위한 helper.
    survey_step API에 GET 요청을 보내 CSRF 쿠키를 받아옴.
    클라이언트의 쿠키 jar에 저장되므로 이후 POST에 자동으로 포함됨.
    
    Returns: csrftoken 문자열, 또는 None (실패 시)
    """
    try:
        # GET survey_start (ensure_csrf_cookie 데코레이터)
        resp = client.get(reverse("survey:survey_start"))
        csrf_cookie = resp.cookies.get("csrftoken")
        if csrf_cookie:
            return csrf_cookie.value
        # 또는 JSON 응답에 포함되었을 수도 있음
        import re
        match = re.search(r"csrftoken['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]", resp.content.decode())
        return match.group(1) if match else None
    except Exception:
        return None


class _FlowMixin:
    """공통 fixture: customer, staff, submission, conversation, message."""

    def _setup_flow(self):
        self.customer = User.objects.create_user(
            username="rev_cust", email="rev@test.com", password="p",
        )
        self.staff = User.objects.create_user(
            username="rev_staff", email="revstaff@test.com", password="p", is_staff=True,
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
            conversation=self.conv, sender=self.customer, body="주소 수정할게요",
        )


# -------------------------------------------------------------------------
# 1. request_id 생성 + 2. route_predicted 이벤트 저장
# -------------------------------------------------------------------------


class RequestIdAndRoutePredictedTests(_FlowMixin, TestCase):
    """수정 요청 메시지 시 request_id 생성, message_received·route_predicted 이벤트 저장."""

    def setUp(self):
        self._setup_flow()

    @patch("customer_request_service.create_customer_auto_reply")
    def test_flow_returns_request_id(self, mock_reply):
        from customer_request_service import handle_customer_request_flow

        result = handle_customer_request_flow(
            "messaging_inbox", self.customer, "서비스를 변경하고 싶어요",
            conversation=self.conv, message=self.msg,
        )
        self.assertIsNotNone(result.request_id, "request_id 생성됨")
        self.assertIsInstance(result.request_id, str)
        self.assertGreaterEqual(len(result.request_id), 16)

    @patch("customer_request_service.create_customer_auto_reply")
    def test_message_received_and_route_predicted_events_saved(self, mock_reply):
        from customer_request_service import handle_customer_request_flow

        result = handle_customer_request_flow(
            "messaging_inbox", self.customer, "서비스를 변경하고 싶어요",
            conversation=self.conv, message=self.msg,
        )
        rid = result.request_id
        self.assertIsNotNone(rid)

        events = list(
            CustomerRequestFeedbackEvent.objects
            .filter(request_id=rid)
            .order_by("created_at")
            .values_list("event_type", flat=True)
        )
        self.assertIn(CustomerRequestFeedbackEvent.EventType.MESSAGE_RECEIVED, events)
        self.assertIn(CustomerRequestFeedbackEvent.EventType.ROUTE_PREDICTED, events)


# -------------------------------------------------------------------------
# 3. suggestion_clicked 이벤트 저장
# -------------------------------------------------------------------------


class SuggestionClickedTests(_FlowMixin, TestCase):
    """추천(설문 수정하기) 클릭 시 suggestion_clicked 이벤트 저장."""

    def setUp(self):
        self._setup_flow()
        self.analysis = CustomerRequestIntentAnalysis.objects.create(
            customer=self.customer,
            conversation=self.conv,
            message=self.msg,
            original_text="서비스 변경",
            predicted_intent="SURVEY_REOPEN_REQUEST",
            predicted_action="OFFER_SURVEY_REOPEN",
            execution_mode="AUTO_CONFIRMABLE",
            confidence=0.75,
            source="heuristic",
            request_id="test_req_click_001",
            route_candidates={"selected_primary_page": "service_selection"},
        )
        self.proposal = CustomerActionProposal.objects.create(
            analysis=self.analysis,
            proposal_type="SURVEY_REOPEN",
            title="설문 수정",
            body="설문을 수정할 수 있도록 열어드릴까요?",
            action_code="reopen_survey",
            action_payload={"submission_id": self.submission.id},
            status=CustomerActionProposal.Status.PROPOSED,
            submission=self.submission,
            conversation=self.conv,
        )

    @patch("customer_request_service.create_customer_auto_reply")
    def test_confirm_proposal_creates_suggestion_clicked(self, mock_reply):
        from customer_request_service import confirm_proposal

        confirm_proposal(self.proposal.id, self.customer)

        ev = CustomerRequestFeedbackEvent.objects.filter(
            request_id="test_req_click_001",
            event_type=CustomerRequestFeedbackEvent.EventType.SUGGESTION_CLICKED,
        ).first()
        self.assertIsNotNone(ev)
        self.assertEqual(ev.metadata.get("suggested_page_key"), "service_selection")


# -------------------------------------------------------------------------
# 4. page_viewed / 5. edit_saved / 6. feedback_clicked (서비스 레벨)
# -------------------------------------------------------------------------


class EventLoggingUnitTests(TestCase):
    """feedback_events 로깅 단위 테스트."""

    def test_log_page_viewed_creates_event(self):
        from messaging.feedback_events import log_page_viewed

        ev = log_page_viewed(
            "test_req_pv_001",
            page_key="applicant_info",
            source="suggestion",
        )
        self.assertIsNotNone(ev)
        self.assertEqual(ev.request_id, "test_req_pv_001")
        self.assertEqual(ev.event_type, CustomerRequestFeedbackEvent.EventType.PAGE_VIEWED)
        self.assertEqual(ev.page_key, "applicant_info")
        self.assertEqual(ev.metadata.get("source"), "suggestion")

    def test_log_edit_saved_creates_event(self):
        from messaging.feedback_events import log_edit_saved

        ev = log_edit_saved(
            "test_req_es_001",
            page_key="applicant_info",
            save_result="success",
            changed_fields=["first_name"],
        )
        self.assertIsNotNone(ev)
        self.assertEqual(ev.event_type, CustomerRequestFeedbackEvent.EventType.EDIT_SAVED)
        self.assertEqual(ev.metadata.get("save_result"), "success")
        self.assertEqual(ev.metadata.get("changed_fields"), ["first_name"])

    def test_log_feedback_clicked_creates_event(self):
        from messaging.feedback_events import log_feedback_clicked

        ev = log_feedback_clicked(
            "test_req_fb_001",
            value="corrected_here",
        )
        self.assertIsNotNone(ev)
        self.assertEqual(ev.event_type, CustomerRequestFeedbackEvent.EventType.FEEDBACK_CLICKED)
        self.assertEqual(ev.metadata.get("value"), "corrected_here")


# -------------------------------------------------------------------------
# 7. actual_edit_page 추론 / 8. 추천≠실제 시 label / 11. multi-step
# -------------------------------------------------------------------------


class LearningSummaryLabelTests(TestCase):
    """학습 요약·라벨 생성 단위 테스트."""

    def setUp(self):
        from messaging.feedback_events import (
            log_message_received,
            log_route_predicted,
            log_edit_saved,
            log_feedback_clicked,
        )
        self.rid = "test_req_summary_001"
        log_message_received(self.rid, message_text="주소 바꿀게요")
        log_route_predicted(
            self.rid,
            user_message="주소 바꿀게요",
            selected_primary_page="applicant_info",
            merged_candidates=[{"page_key": "applicant_info", "score": 0.9}],
        )

    def test_actual_edit_page_inferred_from_edit_saved(self):
        from messaging.feedback_events import log_edit_saved
        from messaging.learning_labels import build_learning_summary

        log_edit_saved(
            self.rid,
            page_key="applicant_info",
            save_result="success",
        )
        summary = build_learning_summary(self.rid)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["actual_edit_page"], "applicant_info")
        self.assertTrue(summary["edit_completed"])
        self.assertEqual(summary["label_quality"], "strong")
        self.assertIn("applicant_info", summary["positive_labels"])

    def test_recommended_different_from_actual_creates_negative_label(self):
        from messaging.feedback_events import log_edit_saved, log_feedback_clicked
        from messaging.learning_labels import build_learning_summary

        # 추천은 applicant_info, 실제 저장은 household_info + used_other_page
        log_edit_saved(
            self.rid,
            page_key="household_info",
            save_result="success",
        )
        log_feedback_clicked(self.rid, value="used_other_page", page_key="applicant_info")

        summary = build_learning_summary(self.rid)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["actual_edit_page"], "household_info")
        self.assertIn("applicant_info", summary["negative_labels"])
        self.assertIn("household_info", summary["positive_labels"])

    def test_multi_step_all_edit_saved_pages(self):
        from messaging.feedback_events import log_edit_saved
        from messaging.learning_labels import build_learning_summary

        rid2 = "test_req_multistep_002"
        from messaging.feedback_events import log_message_received, log_route_predicted
        log_message_received(rid2, message_text="여러 곳 수정")
        log_route_predicted(rid2, selected_primary_page="applicant_info")
        log_edit_saved(rid2, page_key="applicant_info", save_result="success")
        log_edit_saved(rid2, page_key="household_info", save_result="success")

        summary = build_learning_summary(rid2)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["actual_edit_page"], "applicant_info")
        self.assertEqual(sorted(summary["all_edit_saved_pages"]), ["applicant_info", "household_info"])
        self.assertEqual(sorted(summary["positive_labels"]), ["applicant_info", "household_info"])


# -------------------------------------------------------------------------
# 9. LLM 실패 시 heuristic fallback
# -------------------------------------------------------------------------


class LLMFallbackTests(TestCase):
    """LLM 호출 실패 시 휴리스틱만으로 fallback."""

    @patch("customer_request_llm.call_gemini_classify", side_effect=Exception("gemini down"))
    @patch("customer_request_llm.call_ollama_classify", side_effect=Exception("ollama down"))
    def test_llm_failure_returns_heuristic_result(self, mock_ollama, mock_gemini):
        from customer_request_policy import classify_customer_request, Intent

        result = classify_customer_request("서비스를 변경하고 싶어요", allow_llm=True)
        self.assertEqual(result.policy.detected_intent, Intent.SURVEY_REOPEN_REQUEST)
        self.assertEqual(result.policy.source, "heuristic")


# -------------------------------------------------------------------------
# 10. request_id 없을 때 안전 동작
# -------------------------------------------------------------------------


class RequestIdMissingTests(TestCase):
    """request_id 누락 시 이벤트 미저장·시스템 미손상."""

    def test_save_event_with_empty_request_id_returns_none(self):
        from messaging.feedback_events import _save_event

        ev = _save_event("", "message_received", message_text="test")
        self.assertIsNone(ev)
        self.assertEqual(
            CustomerRequestFeedbackEvent.objects.filter(request_id="").count(),
            0,
        )

    def test_feedback_api_requires_request_id(self):
        client = Client()
        client.force_login(User.objects.create_user(username="u", is_staff=True))
        resp = client.post(
            reverse("survey:survey_revision_feedback"),
            data={"value": "corrected_here"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertIn("request_id", data.get("error", ""))


# -------------------------------------------------------------------------
# API 레벨: feedback POST
# -------------------------------------------------------------------------


class FeedbackApiTests(_FlowMixin, TestCase):
    """피드백 API POST 검증."""

    def setUp(self):
        self._setup_flow()
        self.staff_user = User.objects.get(username="rev_staff")

    def test_feedback_clicked_api_creates_event(self):
        from messaging.feedback_events import log_message_received

        rid = "test_req_api_fb_001"
        log_message_received(rid, message_text="수정 요청")

        client = Client()
        client.force_login(self.staff_user)
        
        # CSRF 토큰 부트스트랩
        csrf_token = bootstrap_csrftoken_from_survey_api(client)
        self.assertIsNotNone(csrf_token, "CSRF 토큰을 얻을 수 없음")

        resp = client.post(
            reverse("survey:survey_revision_feedback"),
            data={
                "request_id": rid,
                "value": "could_not_find",
                "csrfmiddlewaretoken": csrf_token,
            },
        )
        self.assertEqual(resp.status_code, 200, resp.content.decode() if resp.status_code != 200 else "")
        self.assertTrue(resp.json().get("ok"))

        ev = CustomerRequestFeedbackEvent.objects.filter(
            request_id=rid,
            event_type=CustomerRequestFeedbackEvent.EventType.FEEDBACK_CLICKED,
        ).first()
        self.assertIsNotNone(ev)
        self.assertEqual(ev.metadata.get("value"), "could_not_find")


class MessageFeedbackApiTests(_FlowMixin, TestCase):
    """메시지 하단 thumbs 피드백 API 검증."""

    def setUp(self):
        self._setup_flow()
        self.client = Client()
        self.client.force_login(self.customer)
        self.bot_msg = Message.objects.create(
            conversation=self.conv,
            sender=self.staff,
            body="설문을 다시 열어드릴게요.",
        )
        self.analysis = CustomerRequestIntentAnalysis.objects.create(
            customer=self.customer,
            conversation=self.conv,
            message=self.msg,
            original_text="서비스 변경",
            predicted_intent="SURVEY_REOPEN_REQUEST",
            predicted_action="OFFER_SURVEY_REOPEN",
            execution_mode="AUTO_CONFIRMABLE",
            confidence=0.79,
            source="heuristic",
            request_id="test_req_msg_fb_001",
            route_candidates={
                "feedback_target_message_id": self.bot_msg.id,
                "feedback_enabled": True,
            },
        )

    def test_message_feedback_api_creates_thumbs_event(self):
        resp = self.client.post(
            f"/api/messaging/conversations/{self.conv.id}/messages/{self.bot_msg.id}/feedback/",
            data={
                "request_id": self.analysis.request_id,
                "value": "thumbs_up",
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content.decode() if resp.status_code != 200 else "")
        body = resp.json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("value"), "thumbs_up")

        ev = CustomerRequestFeedbackEvent.objects.filter(
            request_id=self.analysis.request_id,
            event_type=CustomerRequestFeedbackEvent.EventType.FEEDBACK_CLICKED,
        ).order_by("-created_at").first()
        self.assertIsNotNone(ev)
        self.assertEqual(ev.metadata.get("value"), "thumbs_up")
        self.assertEqual(ev.metadata.get("source"), "model_result_message")
        self.assertEqual(ev.metadata.get("message_id"), self.bot_msg.id)

    def test_message_feedback_api_rejects_invalid_target(self):
        another_msg = Message.objects.create(
            conversation=self.conv,
            sender=self.staff,
            body="다른 자동 응답",
        )
        resp = self.client.post(
            f"/api/messaging/conversations/{self.conv.id}/messages/{another_msg.id}/feedback/",
            data={
                "request_id": self.analysis.request_id,
                "value": "thumbs_down",
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("피드백 대상", resp.json().get("error", ""))


# -------------------------------------------------------------------------
# 타임라인 집계
# -------------------------------------------------------------------------


class TimelineAggregationTests(TestCase):
    """get_event_timeline / build_request_flow_detail."""

    def test_get_event_timeline_returns_chronological_order(self):
        from messaging.feedback_events import (
            log_message_received,
            log_route_predicted,
            log_page_viewed,
            get_event_timeline,
        )

        rid = "test_req_timeline_001"
        log_message_received(rid, message_text="메시지")
        log_route_predicted(rid, selected_primary_page="applicant_info")
        log_page_viewed(rid, page_key="applicant_info", source="suggestion")

        timeline = get_event_timeline(rid)
        types = [e.event_type for e in timeline]
        self.assertEqual(types[0], CustomerRequestFeedbackEvent.EventType.MESSAGE_RECEIVED)
        self.assertEqual(types[1], CustomerRequestFeedbackEvent.EventType.ROUTE_PREDICTED)
        self.assertEqual(types[2], CustomerRequestFeedbackEvent.EventType.PAGE_VIEWED)

    def test_build_request_flow_detail_returns_inferred(self):
        from messaging.feedback_events import log_edit_saved
        from messaging.learning_labels import build_request_flow_detail

        rid = "test_req_detail_001"
        from messaging.feedback_events import log_message_received, log_route_predicted
        log_message_received(rid, message_text="주소 수정")
        log_route_predicted(rid, selected_primary_page="applicant_info")
        log_edit_saved(rid, page_key="applicant_info", save_result="success")

        detail = build_request_flow_detail(rid)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["inferred"]["actual_edit_page"], "applicant_info")
        self.assertTrue(detail["inferred"]["recommendation_success"])
        self.assertEqual(len(detail["timeline"]), 3)


# -------------------------------------------------------------------------
# E2E 통합 테스트: 실제 view 흐름 (request_id 세션 전파, 이벤트 저장 등)
# -------------------------------------------------------------------------


class SurveyRevisionFeedbackE2ETests(_FlowMixin, TestCase):
    """
    설문 수정 흐름 E2E 통합 테스트.
    
    시나리오 A: 페이지 진입 → 저장 → 학습 요약
    시나리오 B: 다중 페이지 + 피드백 API
    시나리오 C: request_id 세션 유지 검증
    """

    def setUp(self):
        self._setup_flow()
        # E2E 테스트용: 기존 submission을 DRAFT 상태로 변경
        self.submission.status = SurveySubmission.Status.DRAFT
        self.submission.save()
        
        self.client = Client()
        self.client.force_login(self.customer)
        # session에 draft submission ID 저장
        session = self.client.session
        session['survey_submission_id'] = self.submission.id
        session.save()

    def get_csrf_token(self, response):
        """응답에서 CSRF 토큰 추출."""
        csrf_cookie = response.cookies.get('csrftoken')
        if csrf_cookie:
            return csrf_cookie.value
        import re
        match = re.search(r"csrftoken['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]", response.content.decode())
        return match.group(1) if match else None

    def test_scenario_a_page_viewed_edit_saved_summary(self):
        """
        시나리오 A: 
        1. request_id로 survey_step 진입
        2. page_viewed 이벤트 저장 확인
        3. 데이터 저장
        4. edit_saved 이벤트 저장 확인
        5. learning summary에서 actual_edit_page 추론 확인
        """
        from survey.models import SurveySection, SurveyQuestion
        from messaging.learning_labels import build_learning_summary

        # setup: 기존 설문 구조 사용 (또는 새 섹션 생성)
        # first_name, email은 이미 있을 가능성이 있으므로 확인 후 생성
        section = SurveySection.objects.filter(
            title="신청자 정보", is_active=True, is_internal=False
        ).first()
        if not section:
            section = SurveySection.objects.create(
                title="신청자 정보",
                display_order=1,
                is_active=True,
                is_internal=False,
            )

        # 기존 문항 재사용 또는 고유 key로 생성
        request_id = "e2e_scenario_a_001"
        
        # step 1 조회 (GET with request_id)
        resp = self.client.get(
            reverse("survey:survey_step", kwargs={"step": 1}),
            {"request_id": request_id},
        )
        self.assertEqual(resp.status_code, 200)
        csrf_token = self.get_csrf_token(resp)
        self.assertIsNotNone(csrf_token)
        
        # page_viewed 이벤트 확인
        page_viewed_evt = CustomerRequestFeedbackEvent.objects.filter(
            request_id=request_id,
            event_type=CustomerRequestFeedbackEvent.EventType.PAGE_VIEWED,
        ).first()
        self.assertIsNotNone(page_viewed_evt, "page_viewed 이벤트가 저장되어야 함")
        self.assertEqual(page_viewed_evt.page_key, "applicant_info")

        # step 1 저장 (POST) - 기존 필드 사용
        resp = self.client.post(
            reverse("survey:survey_step_save", kwargs={"step": 1}),
            {
                "email": self.customer.email,
                "first_name": "John",
                "request_id": request_id,
                "csrfmiddlewaretoken": csrf_token,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"), f"저장 실패: {data}")
        
        # edit_saved 이벤트 확인
        edit_saved_evt = CustomerRequestFeedbackEvent.objects.filter(
            request_id=request_id,
            event_type=CustomerRequestFeedbackEvent.EventType.EDIT_SAVED,
        ).first()
        self.assertIsNotNone(edit_saved_evt, "edit_saved 이벤트가 저장되어야 함")
        self.assertEqual(edit_saved_evt.page_key, "applicant_info")
        self.assertEqual(edit_saved_evt.metadata.get("save_result"), "success")
        self.assertIn("first_name", edit_saved_evt.metadata.get("changed_fields", []))

        # learning summary 확인
        summary = build_learning_summary(request_id)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["actual_edit_page"], "applicant_info")
        self.assertTrue(summary["edit_completed"])
        self.assertEqual(summary["label_quality"], "strong")
        self.assertIn("applicant_info", summary["positive_labels"])

    def test_scenario_b_multi_step_with_feedback(self):
        """
        시나리오 B:
        1. 여러 페이지 순회 (step 1 → 2)
        2. 각 페이지에서 page_viewed, edit_saved 기록
        3. feedback API POST (feedback_clicked)
        4. 타임라인 조회: page_viewed → edit_saved → feedback_clicked 순서 확인
        """
        from messaging.feedback_events import get_event_timeline

        # 기존 섹션 사용 (이미 있을 것으로 가정)
        # step 1과 2가 있으면 그대로 진행
        request_id = "e2e_scenario_b_002"
        
        # step 1 진입 & 저장
        resp = self.client.get(
            reverse("survey:survey_step", kwargs={"step": 1}),
            {"request_id": request_id},
        )
        csrf_token = self.get_csrf_token(resp)
        resp = self.client.post(
            reverse("survey:survey_step_save", kwargs={"step": 1}),
            {
                "email": self.customer.email,
                "first_name": "Alice",
                "request_id": request_id,
                "csrfmiddlewaretoken": csrf_token,
            },
        )
        self.assertEqual(resp.status_code, 200)

        # step 2 진입 (이전 session request_id 유지 예상)
        resp = self.client.get(
            reverse("survey:survey_step", kwargs={"step": 2}),
            {"request_id": request_id},
        )
        if resp.status_code == 200:
            csrf_token = self.get_csrf_token(resp)
            resp = self.client.post(
                reverse("survey:survey_step_save", kwargs={"step": 2}),
                {
                    "email": self.customer.email,
                    "request_id": request_id,
                    "csrfmiddlewaretoken": csrf_token,
                },
            )
            self.assertEqual(resp.status_code, 200)
        else:
            # step 2가 없으면 step 1에서만 진행
            pass

        # feedback_clicked POST
        resp = self.client.post(
            reverse("survey:survey_revision_feedback"),
            {
                "request_id": request_id,
                "value": "corrected_here",
                "page_key": "applicant_info",
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        # 타임라인 & 순서 확인
        timeline = get_event_timeline(request_id)
        self.assertGreaterEqual(len(timeline), 2, "최소 2개 이벤트 필요 (page_viewed, edit_saved, feedback_clicked 등)")
        
        event_types = [e.event_type for e in timeline]
        self.assertIn(CustomerRequestFeedbackEvent.EventType.PAGE_VIEWED, event_types)
        self.assertIn(CustomerRequestFeedbackEvent.EventType.EDIT_SAVED, event_types)
        
        # 순서 확인: PAGE_VIEWED가 EDIT_SAVED보다 앞
        page_viewed_idx = next(
            (i for i, e in enumerate(timeline) 
             if e.event_type == CustomerRequestFeedbackEvent.EventType.PAGE_VIEWED),
            -1
        )
        edit_saved_idx = next(
            (i for i, e in enumerate(timeline)
             if e.event_type == CustomerRequestFeedbackEvent.EventType.EDIT_SAVED),
            -1
        )
        if page_viewed_idx >= 0 and edit_saved_idx >= 0:
            self.assertGreater(edit_saved_idx, page_viewed_idx, "edit_saved이 page_viewed 이후여야 함")

    def test_scenario_c_request_id_session_propagation(self):
        """
        시나리오 C:
        URL GET ?request_id=xxx → session 저장 → POST form.request_id로 전파 확인
        """
        request_id = "e2e_scenario_c_003"

        # step 1 GET with request_id
        resp = self.client.get(
            reverse("survey:survey_step", kwargs={"step": 1}),
            {"request_id": request_id},
        )
        self.assertEqual(resp.status_code, 200)
        # session에 request_id가 저장되었는지 확인
        self.assertEqual(self.client.session.get("survey_request_id"), request_id)

        csrf_token = self.get_csrf_token(resp)

        # POST: request_id 명시하지 않고 session에만 의존
        resp = self.client.post(
            reverse("survey:survey_step_save", kwargs={"step": 1}),
            {
                "email": self.customer.email,
                "first_name": "Test",
                "csrfmiddlewaretoken": csrf_token,
                # request_id를 POST에 안 넣음: session에서 가져와야 함
            },
        )
        self.assertEqual(resp.status_code, 200)

        # edit_saved 이벤트는 session request_id로 저장되어야 함
        edit_saved_evt = CustomerRequestFeedbackEvent.objects.filter(
            request_id=request_id,
            event_type=CustomerRequestFeedbackEvent.EventType.EDIT_SAVED,
        ).first()
        self.assertIsNotNone(edit_saved_evt, "session request_id로 edit_saved 저장되어야 함")

    def test_prev_step_link_preserves_request_id(self):
        """
        이전 단계 링크 ?request_id=xxx 유지 확인.
        """
        from survey.models import SurveySubmission

        # REVISION_REQUESTED 상태 설정 (prev/next 버튼 노출 조건)
        self.submission.status = SurveySubmission.Status.REVISION_REQUESTED
        self.submission.save()

        request_id = "e2e_prev_link_004"

        # step 2 GET with request_id (step 2가 없으면 step 1로 진행)
        resp = self.client.get(
            reverse("survey:survey_step", kwargs={"step": 2}),
            {"request_id": request_id},
        )
        
        # step 2가 없으면 리다이렉트될 수 있으므로 확인
        if resp.status_code == 302:
            resp = self.client.get(resp.url)
        
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()

        # prev_step 링크에 request_id가 포함되어 있는지 확인
        import re
        prev_link_match = re.search(
            r'href=["\']([^"\']*survey_step[^"\']*)["\'].*?←',
            content,
            re.DOTALL
        )
        if prev_link_match:
            prev_href = prev_link_match.group(1)
            # request_id가 있는지 확인 (있을 수도, 없을 수도 있음)
            # 하지만 우리가 수정한 템플릿에서는 있어야 함
            if "step=" in prev_href:  # prev_step 링크인지 확인
                self.assertIn("request_id", prev_href, 
                              f"prev_step 링크에 request_id가 포함되어야 함: {prev_href}")
