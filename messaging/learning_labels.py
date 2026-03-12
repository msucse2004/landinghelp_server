"""
request_id 단위 이벤트 집계 및 학습용 label/summary 생성.

우선순위 규칙:
1. edit_saved success 발생 page_key → strongest positive label
2. suggestion_clicked만 있고 edit_saved 없음 → weak positive
3. page_viewed 후 빠른 이탈 → weak negative 후보 (viewed_pages에 기록, 추후 dwell time으로 보강 가능)
4. feedback_clicked = used_other_page 이고 다른 page에서 edit_saved → 추천 페이지는 negative
5. feedback_clicked = could_not_find → recommendation failure

Multi-step(여러 페이지 연속 수정):
- actual_edit_page: 첫 번째 edit_saved success 페이지(단일 대표값). UI/요약 표시용.
- all_edit_saved_pages: 해당 request_id 내 모든 edit_saved success 페이지 리스트.
- 학습 시 multi-step 요청은 all_edit_saved_pages(및 positive_labels)를 사용.
- 동일 request_id에 여러 edit_saved가 있어도 모두 수집하며, negative_labels는
  used_other_page + 추천≠실제 페이지일 때만 추천 페이지를 negative로 기록.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta
from typing import Any, Dict, List, Optional

from django.utils import timezone

from .feedback_events import get_event_timeline
from .models import CustomerRequestFeedbackEvent

logger = logging.getLogger(__name__)

# label_quality: supervised learning 예제 품질
LABEL_QUALITY_STRONG = "strong"   # edit_saved success 있음 (ground truth)
LABEL_QUALITY_MEDIUM = "medium"   # feedback_clicked 있음 (corrected_here / used_other_page)
LABEL_QUALITY_WEAK = "weak"       # suggestion_clicked 또는 page_viewed만 있음


def build_learning_summary(
    request_id: str,
    *,
    timeline: Optional[List[CustomerRequestFeedbackEvent]] = None,
) -> Optional[Dict[str, Any]]:
    """
    request_id에 해당하는 이벤트를 모아 학습용 summary 객체를 생성한다.

    반환 summary 필드:
    - request_id, user_message, predicted_primary_page, predicted_candidates
    - clicked_pages, viewed_pages
    - actual_edit_page (단일: 첫 edit_saved 페이지), edit_completed, all_edit_saved_pages (전체 리스트)
    - feedback_type (corrected_here | used_other_page | could_not_find | None)
    - label_quality (strong | medium | weak)
    - positive_labels, negative_labels (학습용)
    - recommendation_failure (bool)

    예외: 이벤트 없음/request_id 누락 시 None. 메타데이터 형식 이상 시 해당 필드만 스킵.
    """
    rid = (request_id or "").strip()
    if not rid:
        logger.debug("build_learning_summary: empty request_id")
        return None

    events = timeline if timeline is not None else get_event_timeline(rid)
    if not events:
        logger.debug("build_learning_summary: no events for request_id=%s", rid[:16] if rid else "")
        return None

    # ---- 추출 ----
    user_message = ""
    predicted_primary_page = ""
    predicted_candidates: List[Dict[str, Any]] = []

    clicked_pages: List[str] = []
    viewed_pages: List[Dict[str, Any]] = []  # [{page_key, viewed_at, source}, ...]

    edit_saved_success_pages: List[str] = []  # page_key where save_result == success
    feedback_type: Optional[str] = None  # corrected_here | used_other_page | could_not_find
    model_feedback_value: Optional[str] = None  # thumbs_up | thumbs_down

    for ev in events:
        meta = ev.metadata if isinstance(getattr(ev, "metadata", None), dict) else {}
        if ev.event_type == CustomerRequestFeedbackEvent.EventType.MESSAGE_RECEIVED:
            if ev.message_text and not user_message:
                user_message = (ev.message_text or "").strip()
        elif ev.event_type == CustomerRequestFeedbackEvent.EventType.ROUTE_PREDICTED:
            if not predicted_primary_page:
                predicted_primary_page = (meta.get("selected_primary_page") or ev.page_key or "").strip()
            if not predicted_candidates and "merged_candidates" in meta:
                raw = meta["merged_candidates"]
                if isinstance(raw, list):
                    predicted_candidates = [c if isinstance(c, dict) else {} for c in raw[:20]]
            if not user_message and meta.get("user_message"):
                user_message = (meta.get("user_message") or "").strip()
        elif ev.event_type == CustomerRequestFeedbackEvent.EventType.SUGGESTION_CLICKED:
            pk = (meta.get("suggested_page_key") or ev.page_key or "").strip()
            if pk and pk not in clicked_pages:
                clicked_pages.append(pk)
        elif ev.event_type == CustomerRequestFeedbackEvent.EventType.PAGE_VIEWED:
            pk = (ev.page_key or meta.get("page_key") or "").strip()
            if pk:
                viewed_at = (meta.get("viewed_at") or "").strip() or (ev.created_at.isoformat() if ev.created_at else "")
                source = (meta.get("source") or "").strip() or "manual_navigation"
                viewed_pages.append({"page_key": pk, "viewed_at": viewed_at, "source": source})
        elif ev.event_type == CustomerRequestFeedbackEvent.EventType.EDIT_SAVED:
            if meta.get("save_result") == "success":
                pk = (ev.page_key or meta.get("page_key") or "").strip()
                if pk and pk not in edit_saved_success_pages:
                    edit_saved_success_pages.append(pk)
        elif ev.event_type == CustomerRequestFeedbackEvent.EventType.FEEDBACK_CLICKED:
            value = (meta.get("value") or "").strip() or None
            if (meta.get("source") or "").strip() == "model_result_message":
                model_feedback_value = value
            else:
                feedback_type = value

    # ---- 파생 ----
    edit_completed = len(edit_saved_success_pages) > 0
    actual_edit_page = edit_saved_success_pages[0] if edit_saved_success_pages else None

    # positive_labels: 학습용 positive (실제 수정한 페이지 우선, 없으면 클릭만 한 페이지를 weak으로)
    positive_labels: List[str] = []
    if edit_saved_success_pages:
        positive_labels = list(edit_saved_success_pages)
    elif clicked_pages:
        positive_labels = list(clicked_pages)  # weak positive
    elif model_feedback_value == "thumbs_up" and predicted_primary_page:
        positive_labels = [predicted_primary_page]

    # negative_labels: 추천했는데 사용자가 다른 페이지에서 수정한 경우
    negative_labels: List[str] = []
    if (
        feedback_type == "used_other_page"
        and predicted_primary_page
        and actual_edit_page
        and predicted_primary_page != actual_edit_page
    ):
        if predicted_primary_page not in negative_labels:
            negative_labels.append(predicted_primary_page)
    if model_feedback_value == "thumbs_down" and predicted_primary_page and predicted_primary_page not in negative_labels:
        negative_labels.append(predicted_primary_page)

    recommendation_failure = feedback_type == "could_not_find"

    # label_quality
    if edit_completed:
        label_quality = LABEL_QUALITY_STRONG
    elif feedback_type or model_feedback_value:
        label_quality = LABEL_QUALITY_MEDIUM
    else:
        label_quality = LABEL_QUALITY_WEAK

    return {
        "request_id": rid,
        "user_message": user_message,
        "predicted_primary_page": predicted_primary_page,
        "predicted_candidates": predicted_candidates,
        "clicked_pages": clicked_pages,
        "viewed_pages": viewed_pages,
        "actual_edit_page": actual_edit_page,
        "edit_completed": edit_completed,
        "all_edit_saved_pages": edit_saved_success_pages,
        "feedback_type": feedback_type,
        "model_feedback_value": model_feedback_value,
        "label_quality": label_quality,
        "positive_labels": positive_labels,
        "negative_labels": negative_labels,
        "recommendation_failure": recommendation_failure,
    }


def get_or_build_learning_summary(
    request_id: str,
    *,
    save: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    request_id에 대한 learning summary를 반환한다.
    save=True이면 CustomerRequestLearningSummary에 저장(upsert)한다.
    """
    summary = build_learning_summary(request_id)
    if not summary:
        return None
    if save:
        try:
            from .models import CustomerRequestLearningSummary
            rid = summary.get("request_id") or (request_id or "").strip()
            CustomerRequestLearningSummary.objects.update_or_create(
                request_id=rid,
                defaults={
                    "summary": summary,
                    "label_quality": summary.get("label_quality") or LABEL_QUALITY_WEAK,
                },
            )
        except Exception as e:
            logger.warning(
                "learning_labels: save summary failed request_id=%s: %s",
                summary.get("request_id", request_id), e,
                exc_info=True,
            )
        # 새 피드백이 저장됐으므로 추천 점수 캐시 무효화 (다음 classify 호출 시 재조회)
        try:
            from .feedback_scores import invalidate_feedback_score_cache
            invalidate_feedback_score_cache()
        except Exception:
            pass
    return summary


# ---------------------------------------------------------------------------
# Admin/Debug: request_id 기준 상세 흐름 (타임라인 + 추천 품질)
# ---------------------------------------------------------------------------


def build_request_flow_detail(
    request_id: str,
    *,
    timeline: Optional[List[CustomerRequestFeedbackEvent]] = None,
) -> Optional[Dict[str, Any]]:
    """
    request_id에 대한 디버그용 상세 흐름을 반환.
    - 타임라인(시간순 이벤트), 휴리스틱/LLM 결과, 추천 후보
    - suggestion_clicked / page_viewed / edit_saved / feedback_clicked 목록
    - inferred actual target, recommendation success/failure
    개인정보: message_text는 요약만 노출(길이 제한). user_id 등은 제외.
    """
    rid = (request_id or "").strip()
    if not rid:
        return None

    events = timeline if timeline is not None else get_event_timeline(rid)
    if not events:
        return None

    summary = build_learning_summary(rid, timeline=events)
    if not summary:
        summary = {}

    # 첫 route_predicted에서 추출
    user_message = ""
    heuristic_result: Optional[Dict[str, Any]] = None
    llm_result: Optional[Dict[str, Any]] = None
    predicted_candidates: List[Dict[str, Any]] = []
    selected_primary_page = ""

    suggestion_clicked_list: List[Dict[str, Any]] = []
    page_viewed_list: List[Dict[str, Any]] = []
    edit_saved_list: List[Dict[str, Any]] = []
    feedback_clicked: Optional[Dict[str, Any]] = None

    timeline_out: List[Dict[str, Any]] = []

    for ev in events:
        meta = ev.metadata if isinstance(getattr(ev, "metadata", None), dict) else {}
        at = ev.created_at.isoformat() if ev.created_at else ""

        # 타임라인 항목 (개인정보 최소화: message_text는 앞 100자만)
        item = {
            "event_type": ev.event_type,
            "at": at,
        }
        if ev.page_key:
            item["page_key"] = ev.page_key
        if ev.message_text:
            msg = (ev.message_text or "")[:100]
            if len(ev.message_text or "") > 100:
                msg += "..."
            item["message_preview"] = msg
        timeline_out.append(item)

        if ev.event_type == CustomerRequestFeedbackEvent.EventType.MESSAGE_RECEIVED:
            if ev.message_text and not user_message:
                user_message = (ev.message_text or "").strip()[:500]
        elif ev.event_type == CustomerRequestFeedbackEvent.EventType.ROUTE_PREDICTED:
            if not selected_primary_page:
                selected_primary_page = (meta.get("selected_primary_page") or ev.page_key or "").strip()
            if meta.get("user_message") and not user_message:
                user_message = (str(meta.get("user_message")) or "").strip()[:500]
            if "heuristic_result" in meta and heuristic_result is None:
                heuristic_result = meta.get("heuristic_result")
            if "llm_result" in meta and llm_result is None:
                llm_result = meta.get("llm_result")
            if not predicted_candidates and "merged_candidates" in meta:
                raw = meta["merged_candidates"]
                if isinstance(raw, list):
                    predicted_candidates = [c if isinstance(c, dict) else {} for c in raw[:20]]
        elif ev.event_type == CustomerRequestFeedbackEvent.EventType.SUGGESTION_CLICKED:
            suggestion_clicked_list.append({
                "at": at,
                "suggested_page_key": (meta.get("suggested_page_key") or ev.page_key or "").strip(),
                "clicked_item": (meta.get("clicked_item") or "").strip() or None,
            })
        elif ev.event_type == CustomerRequestFeedbackEvent.EventType.PAGE_VIEWED:
            page_viewed_list.append({
                "at": at,
                "page_key": (ev.page_key or meta.get("page_key") or "").strip(),
                "source": (meta.get("source") or "").strip() or "manual_navigation",
            })
        elif ev.event_type == CustomerRequestFeedbackEvent.EventType.EDIT_SAVED:
            edit_saved_list.append({
                "at": at,
                "page_key": (ev.page_key or meta.get("page_key") or "").strip(),
                "save_result": meta.get("save_result", ""),
                "changed_fields": meta.get("changed_fields") if isinstance(meta.get("changed_fields"), list) else None,
            })
        elif ev.event_type == CustomerRequestFeedbackEvent.EventType.FEEDBACK_CLICKED:
            feedback_clicked = {
                "at": at,
                "value": (meta.get("value") or "").strip(),
            }

    # recommendation success: 추천이 맞았거나 사용자가 corrected_here 한 경우
    recommendation_failure = summary.get("recommendation_failure", False)
    actual_edit_page = summary.get("actual_edit_page")
    feedback_type = summary.get("feedback_type")
    recommendation_success = (
        not recommendation_failure
        and (
            feedback_type == "corrected_here"
            or (actual_edit_page and selected_primary_page and actual_edit_page == selected_primary_page)
        )
    )

    return {
        "request_id": rid,
        "user_message": user_message[:500] if user_message else "",
        "heuristic_result": heuristic_result,
        "llm_result": llm_result,
        "predicted_candidates": predicted_candidates,
        "selected_primary_page": selected_primary_page,
        "suggestion_clicked_list": suggestion_clicked_list,
        "page_viewed_list": page_viewed_list,
        "edit_saved_list": edit_saved_list,
        "feedback_clicked": feedback_clicked,
        "inferred": {
            "actual_edit_page": summary.get("actual_edit_page"),
            "all_edit_saved_pages": summary.get("all_edit_saved_pages", []),
            "recommendation_success": recommendation_success,
            "recommendation_failure": recommendation_failure,
            "label_quality": summary.get("label_quality", ""),
            "positive_labels": summary.get("positive_labels", []),
            "negative_labels": summary.get("negative_labels", []),
        },
        "timeline": timeline_out,
    }


def build_manual_label_accuracy_report(limit: int = 20, days: Optional[int] = None) -> Dict[str, Any]:
    """
    관리자 수동 확정 라벨 기준으로 자동 예측 오차를 집계한다.

    반환 필드:
    - total_manual_labeled: 수동 라벨(의도/페이지 중 하나라도 존재) 건수
    - page_mismatch_count: 예측 페이지 != 수동 확정 페이지 건수
    - intent_mismatch_count: 예측 의도 != 수동 확정 의도 건수
    - top_wrong_predicted_pages: [{predicted_page_key, count}]
    - top_target_pages: [{manual_page_key, count}]
    - top_page_mismatch_pairs: [{predicted_page_key, manual_page_key, count}]
    - top_wrong_predicted_intents: [{predicted_intent, count}]
    - top_target_intents: [{manual_intent, count}]
    - top_intent_mismatch_pairs: [{predicted_intent, manual_intent, count}]
    """
    from .models import CustomerRequestIntentAnalysis, CustomerRequestLearningSummary

    cap = max(1, int(limit or 20))
    period_days = int(days) if isinstance(days, int) and days > 0 else None

    qs = CustomerRequestLearningSummary.objects.exclude(manual_confirmed_intent="", manual_confirmed_page_key="")
    if period_days:
        start_at = timezone.now() - timedelta(days=period_days)
        qs = qs.filter(updated_at__gte=start_at)
    else:
        start_at = None

    rows = list(
        qs
        .values("request_id", "summary", "manual_confirmed_intent", "manual_confirmed_page_key")
    )
    if not rows:
        return {
            "total_manual_labeled": 0,
            "period_days": period_days,
            "period_start_at": start_at.isoformat() if start_at else "",
            "page_mismatch_count": 0,
            "intent_mismatch_count": 0,
            "top_wrong_predicted_pages": [],
            "top_target_pages": [],
            "top_page_mismatch_pairs": [],
            "top_wrong_predicted_intents": [],
            "top_target_intents": [],
            "top_intent_mismatch_pairs": [],
        }

    request_ids = [r.get("request_id") for r in rows if r.get("request_id")]
    intent_rows = (
        CustomerRequestIntentAnalysis.objects
        .filter(request_id__in=request_ids)
        .values("request_id", "predicted_intent")
        .order_by("request_id", "-created_at")
    )
    predicted_intent_by_request: Dict[str, str] = {}
    for ir in intent_rows:
        rid = (ir.get("request_id") or "").strip()
        if not rid or rid in predicted_intent_by_request:
            continue
        predicted_intent_by_request[rid] = (ir.get("predicted_intent") or "").strip()

    wrong_predicted_pages = Counter()
    target_pages = Counter()
    page_mismatch_pairs = Counter()

    wrong_predicted_intents = Counter()
    target_intents = Counter()
    intent_mismatch_pairs = Counter()

    page_mismatch_count = 0
    intent_mismatch_count = 0

    for row in rows:
        rid = (row.get("request_id") or "").strip()
        summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}

        predicted_page = (summary.get("predicted_primary_page") or "").strip()
        manual_page = (row.get("manual_confirmed_page_key") or "").strip()
        if manual_page:
            target_pages[manual_page] += 1
        if manual_page and predicted_page and manual_page != predicted_page:
            page_mismatch_count += 1
            wrong_predicted_pages[predicted_page] += 1
            page_mismatch_pairs[(predicted_page, manual_page)] += 1

        predicted_intent = (summary.get("predicted_intent") or "").strip() or predicted_intent_by_request.get(rid, "")
        manual_intent = (row.get("manual_confirmed_intent") or "").strip()
        if manual_intent:
            target_intents[manual_intent] += 1
        if manual_intent and predicted_intent and manual_intent != predicted_intent:
            intent_mismatch_count += 1
            wrong_predicted_intents[predicted_intent] += 1
            intent_mismatch_pairs[(predicted_intent, manual_intent)] += 1

    return {
        "total_manual_labeled": len(rows),
        "period_days": period_days,
        "period_start_at": start_at.isoformat() if start_at else "",
        "page_mismatch_count": page_mismatch_count,
        "intent_mismatch_count": intent_mismatch_count,
        "top_wrong_predicted_pages": [
            {"predicted_page_key": page, "count": count}
            for page, count in wrong_predicted_pages.most_common(cap)
        ],
        "top_target_pages": [
            {"manual_page_key": page, "count": count}
            for page, count in target_pages.most_common(cap)
        ],
        "top_page_mismatch_pairs": [
            {"predicted_page_key": pair[0], "manual_page_key": pair[1], "count": count}
            for pair, count in page_mismatch_pairs.most_common(cap)
        ],
        "top_wrong_predicted_intents": [
            {"predicted_intent": intent, "count": count}
            for intent, count in wrong_predicted_intents.most_common(cap)
        ],
        "top_target_intents": [
            {"manual_intent": intent, "count": count}
            for intent, count in target_intents.most_common(cap)
        ],
        "top_intent_mismatch_pairs": [
            {"predicted_intent": pair[0], "manual_intent": pair[1], "count": count}
            for pair, count in intent_mismatch_pairs.most_common(cap)
        ],
    }
