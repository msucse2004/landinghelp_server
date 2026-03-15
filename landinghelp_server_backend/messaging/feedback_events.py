"""
설문 수정 흐름 학습용 이벤트 로그 서비스/리포지토리.

- 동일 요청 흐름(request_id) 내에서 message_received → route_predicted → suggestion_clicked
  → page_viewed → edit_saved / feedback_clicked 순으로 이벤트를 기록.
- 추천 페이지 vs 실제 수정 페이지 비교 데이터를 확보해 학습에 활용.

프론트엔드 연동 (request_id 전달):
- 메시지 POST 응답: 성공 시 body.request_id (UUID hex) 포함될 수 있음. 같은 요청 세션 식별용.
- 대화 상세/action_offers: 각 offer에 request_id 필드 있음. 설문 수정하기 클릭 시
  redirect URL에 ?request_id=<request_id> 또는 &request_id=<request_id> 붙여서 이동.
- 설문 step/save/submit: GET은 ?request_id= 로 전달, POST는 form field name="request_id"로 전달.
  request_id 없으면 세션에 없을 때만 이벤트 미기록(graceful fallback).
- 타임라인 조회: get_event_timeline(request_id) 로 해당 세션 이벤트 목록 조회 (내부/관리용).

예외 처리 정책:
- 이벤트 저장 실패 시 로그만 남기고 None 반환(non-blocking). 호출 측 메인 기능은 진행.
- request_id 누락 시 저장 스킵 + warning 로그.
- 저장 예외 시 logger.warning + exc_info로 운영 디버깅 가능.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from django.contrib.auth import get_user_model

from .models import CustomerRequestFeedbackEvent

User = get_user_model()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 공통 필드 및 메타데이터 형식
# ---------------------------------------------------------------------------

def _save_event(
    request_id: str,
    event_type: str,
    *,
    user_id: Optional[int] = None,
    survey_submission_id: Optional[int] = None,
    page_key: Optional[str] = None,
    message_text: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[CustomerRequestFeedbackEvent]:
    """
    이벤트 1건 저장. 실패 시 로그만 남기고 None 반환.
    request_id 누락 시 저장하지 않고 warning 로그 후 None (본 기능은 차단하지 않음).
    """
    rid = (request_id or "").strip()
    if not rid:
        logger.warning(
            "feedback_events: skip save (missing request_id) event_type=%s",
            event_type,
        )
        return None
    try:
        event = CustomerRequestFeedbackEvent.objects.create(
            request_id=rid,
            user_id=user_id,
            survey_submission_id=survey_submission_id,
            event_type=event_type,
            page_key=page_key or None,
            message_text=message_text or None,
            metadata=metadata or {},
        )
        return event
    except Exception as e:
        logger.warning(
            "feedback_events: save failed request_id=%s event_type=%s: %s",
            rid,
            event_type,
            e,
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# 이벤트별 기록 함수
# ---------------------------------------------------------------------------


def log_message_received(
    request_id: str,
    *,
    user_id: Optional[int] = None,
    survey_submission_id: Optional[int] = None,
    message_text: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[CustomerRequestFeedbackEvent]:
    """
    사용자 수정 요청 메시지 수신 이벤트.
    요청 흐름의 첫 이벤트로, request_id는 호출 측에서 생성해 전달.
    """
    return _save_event(
        request_id,
        CustomerRequestFeedbackEvent.EventType.MESSAGE_RECEIVED,
        user_id=user_id,
        survey_submission_id=survey_submission_id,
        message_text=message_text,
        metadata=metadata,
    )


def log_route_predicted(
    request_id: str,
    *,
    user_id: Optional[int] = None,
    survey_submission_id: Optional[int] = None,
    user_message: Optional[str] = None,
    heuristic_result: Optional[Dict[str, Any]] = None,
    llm_result: Optional[Dict[str, Any]] = None,
    merged_candidates: Optional[List[Dict[str, Any]]] = None,
    selected_primary_page: Optional[str] = None,
    recommendation_confidence: Optional[str] = None,
    heuristic_page: Optional[str] = None,
    llm_page: Optional[str] = None,
    top_candidates: Optional[List[Dict[str, Any]]] = None,
    final_recommended_pages: Optional[List[str]] = None,
    metadata_extra: Optional[Dict[str, Any]] = None,
) -> Optional[CustomerRequestFeedbackEvent]:
    """
    경로(추천 페이지) 예측 이벤트.

    metadata에 저장 (학습/ranking용):
    - user_message: 사용자 원문
    - heuristic_result: { candidates, confidence }
    - llm_result: { candidates, confidence, source }
    - merged_candidates: top-k 후보 [{ page_key, score, source, reason }, ...]
    - selected_primary_page: 1순위 페이지(기존 UI용)
    - recommendation_confidence: high | medium | low
    레거시: heuristic_page, llm_page, top_candidates, final_recommended_pages 도 그대로 저장.
    """
    meta = dict(metadata_extra or {})
    if user_message is not None:
        meta["user_message"] = user_message[:2000] if user_message else ""
    if heuristic_result is not None:
        meta["heuristic_result"] = heuristic_result
    if llm_result is not None:
        meta["llm_result"] = llm_result
    if merged_candidates is not None:
        meta["merged_candidates"] = merged_candidates
    if selected_primary_page is not None:
        meta["selected_primary_page"] = selected_primary_page
    if recommendation_confidence is not None:
        meta["recommendation_confidence"] = recommendation_confidence
    if heuristic_page is not None:
        meta["heuristic_page"] = heuristic_page
    if llm_page is not None:
        meta["llm_page"] = llm_page
    if top_candidates is not None:
        meta["top_candidates"] = top_candidates
    if final_recommended_pages is not None:
        meta["final_recommended_pages"] = final_recommended_pages
    return _save_event(
        request_id,
        CustomerRequestFeedbackEvent.EventType.ROUTE_PREDICTED,
        user_id=user_id,
        survey_submission_id=survey_submission_id,
        metadata=meta,
    )


def log_suggestion_clicked(
    request_id: str,
    *,
    user_id: Optional[int] = None,
    survey_submission_id: Optional[int] = None,
    page_key: Optional[str] = None,
    clicked_item: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[CustomerRequestFeedbackEvent]:
    """
    사용자가 추천 항목(예: 설문 수정하기 버튼)을 클릭한 이벤트.
    page_key 또는 metadata에 어떤 추천을 눌렀는지 저장.
    """
    meta = dict(metadata or {})
    if clicked_item is not None:
        meta["clicked_item"] = clicked_item
    return _save_event(
        request_id,
        CustomerRequestFeedbackEvent.EventType.SUGGESTION_CLICKED,
        user_id=user_id,
        survey_submission_id=survey_submission_id,
        page_key=page_key,
        metadata=meta,
    )


def log_page_viewed(
    request_id: str,
    *,
    user_id: Optional[int] = None,
    survey_submission_id: Optional[int] = None,
    page_key: Optional[str] = None,
    source: Optional[str] = None,
    viewed_at: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[CustomerRequestFeedbackEvent]:
    """
    설문 특정 페이지(step/section) 진입 이벤트. implicit feedback 강화용.

    source: suggestion | manual_navigation | deep_link
      - suggestion: 추천 클릭 후 진입
      - manual_navigation: 이전/다음 등으로 이동
      - deep_link: 직접 링크/북마크로 진입
    viewed_at: ISO 시각 문자열 (미전달 시 서버 저장 시각 사용, 확장 시 dwell 계산에 사용).
    나중에 dwell time 확장 시 metadata에 left_at, dwell_seconds 추가 가능.
    """
    from django.utils import timezone as tz
    meta = dict(metadata or {})
    if source is not None:
        meta["source"] = source
    meta["viewed_at"] = viewed_at if viewed_at else tz.now().isoformat()
    return _save_event(
        request_id,
        CustomerRequestFeedbackEvent.EventType.PAGE_VIEWED,
        user_id=user_id,
        survey_submission_id=survey_submission_id,
        page_key=page_key,
        metadata=meta,
    )


def log_edit_saved(
    request_id: str,
    *,
    user_id: Optional[int] = None,
    survey_submission_id: Optional[int] = None,
    page_key: Optional[str] = None,
    changed_fields: Optional[List[str]] = None,
    save_result: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    metadata_extra: Optional[Dict[str, Any]] = None,
) -> Optional[CustomerRequestFeedbackEvent]:
    """
    특정 페이지에서 수정 저장이 일어난 이벤트 (학습용 strongest label).

    실제로 어떤 페이지에서 저장 API가 성공/실패했는가가 추천 페이지보다 우선하는 정답 레이블.
    metadata에 저장: page_key, changed_fields, save_result, entity_type, entity_id,
    changed_entity_type, changed_entity_id(metadata_extra로 전달 시).

    page_key 예: applicant_info, household_info, region_status, entry_purpose_stay,
    service_selection, delivery_preferences, other_requests, step_N
    """
    meta = dict(metadata_extra or {})
    if page_key is not None:
        meta["page_key"] = page_key
    if changed_fields is not None:
        meta["changed_fields"] = changed_fields
    if save_result is not None:
        meta["save_result"] = save_result
    if entity_type is not None:
        meta["entity_type"] = meta["changed_entity_type"] = entity_type
    if entity_id is not None:
        meta["entity_id"] = meta["changed_entity_id"] = entity_id
    return _save_event(
        request_id,
        CustomerRequestFeedbackEvent.EventType.EDIT_SAVED,
        user_id=user_id,
        survey_submission_id=survey_submission_id,
        page_key=page_key,
        metadata=meta,
    )


def log_feedback_clicked(
    request_id: str,
    value: str,
    *,
    user_id: Optional[int] = None,
    survey_submission_id: Optional[int] = None,
    page_key: Optional[str] = None,
    metadata_extra: Optional[Dict[str, Any]] = None,
) -> Optional[CustomerRequestFeedbackEvent]:
    """
    사용자 피드백 클릭 이벤트.

    value: 다음 중 하나
    - corrected_here: 여기서 수정함
    - used_other_page: 다른 페이지에서 수정함
    - could_not_find: 찾지 못함
    - thumbs_up: 도움됨
    - thumbs_down: 도움 안 됨
    """
    if value not in [v for v, _ in CustomerRequestFeedbackEvent.FeedbackValue.choices]:
        logger.warning("feedback_events: invalid feedback value=%s", value)
    meta = dict(metadata_extra or {})
    meta["value"] = value
    return _save_event(
        request_id,
        CustomerRequestFeedbackEvent.EventType.FEEDBACK_CLICKED,
        user_id=user_id,
        survey_submission_id=survey_submission_id,
        page_key=page_key,
        metadata=meta,
    )


# ---------------------------------------------------------------------------
# 조회 (리포지토리)
# ---------------------------------------------------------------------------


def get_events_by_request(
    request_id: str,
    event_types: Optional[List[str]] = None,
    limit: int = 100,
) -> List[CustomerRequestFeedbackEvent]:
    """
    request_id로 묶인 이벤트 목록 조회. 생성일 역순.
    """
    qs = CustomerRequestFeedbackEvent.objects.filter(request_id=request_id)
    if event_types:
        qs = qs.filter(event_type__in=event_types)
    return list(qs.order_by("-created_at")[:limit])


def get_edit_saved_events_for_submission(
    survey_submission_id: int,
    request_id: Optional[str] = None,
) -> List[CustomerRequestFeedbackEvent]:
    """
    특정 설문 제출에 대해 edit_saved 이벤트만 조회.
    학습 시 "실제로 저장한 페이지" 목록 확보용.
    """
    qs = CustomerRequestFeedbackEvent.objects.filter(
        survey_submission_id=survey_submission_id,
        event_type=CustomerRequestFeedbackEvent.EventType.EDIT_SAVED,
    )
    if request_id:
        qs = qs.filter(request_id=request_id)
    return list(qs.order_by("created_at"))


def get_event_timeline(
    request_id: str,
    limit: int = 200,
) -> List[CustomerRequestFeedbackEvent]:
    """
    request_id 기준 이벤트 타임라인 조회 (발생 시각 순).

    반환: 해당 요청 세션의 message_received → route_predicted → suggestion_clicked
    → page_viewed → edit_saved / feedback_clicked 등 시간순 목록.
    내부 분석·학습·디버깅용.
    """
    return list(
        CustomerRequestFeedbackEvent.objects.filter(request_id=request_id)
        .order_by("created_at")[:limit]
    )
