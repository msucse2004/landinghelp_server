"""
피드백 기반 페이지 키 점수 집계 및 추천 경로 보정.

파이프라인:
1. 사용자가 👍/👎 또는 실제 설문 수정 → CustomerRequestLearningSummary 에 저장
2. rebuild_feedback_scores() 로 전체 summary 집계 → PageKeyFeedbackScore upsert
3. classify_customer_request() 에서 get_feedback_score_boosts() 로 boost 조회
4. _merge_candidates() 에서 base score 에 boost 가중치 적용 → 정확도 높은 page_key 가 상위로

rebuild 트리거:
- 관리자 어드민 액션 "피드백 점수 재계산"
- manage.py rebuild_feedback_scores 명령어
- 새 feedback 저장 후 캐시 무효화 (다음 요청 시 자동 반영)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Django 캐시 키
_CACHE_KEY = "feedback_score_boosts_v1"
_CACHE_TTL = 3600  # 1시간

# 집계 통계에 신뢰도 가중치 적용을 위한 최소 샘플 수
# 이 수 미만이면 boost 가 전체 계산값보다 감쇠됨 (극단치 방지)
_MIN_EVIDENCE = 5


def rebuild_feedback_scores() -> Dict[str, Any]:
    """
    CustomerRequestLearningSummary 전체를 순회해 page_key 별 피드백 통계를 집계하고
    PageKeyFeedbackScore 에 upsert 한다.

    반환: {"updated": int, "page_keys": list}
    """
    from .models import (
        CustomerRequestLearningSummary,
        CustomerRequestManualLabelRevision,
        PageKeyFeedbackScore,
    )

    # {page_key: {thumbs_up, thumbs_down, positive_label, negative_label, seen}}
    stats: Dict[str, Dict[str, int]] = {}

    def _ensure(pk: str) -> None:
        if pk not in stats:
            stats[pk] = {
                "thumbs_up": 0,
                "thumbs_down": 0,
                "positive_label": 0,
                "negative_label": 0,
                "seen": 0,
            }

    for row in CustomerRequestLearningSummary.objects.all().iterator(chunk_size=500):
        s = row.summary if isinstance(row.summary, dict) else {}
        predicted = (s.get("predicted_primary_page") or "").strip()
        auto_positive_labels = [p for p in (s.get("positive_labels") or []) if (p or "").strip()]
        manual_page = (getattr(row, "manual_confirmed_page_key", "") or "").strip()
        if manual_page:
            positive_labels = [manual_page]
        else:
            positive_labels = auto_positive_labels
        negative_labels = [n for n in (s.get("negative_labels") or []) if (n or "").strip()]
        model_feedback = (s.get("model_feedback_value") or "").strip()

        # 수동 확정 페이지가 auto 라벨과 다르면, auto 라벨은 negative 신호로 반영
        if manual_page:
            for auto_page in auto_positive_labels:
                if auto_page and auto_page != manual_page and auto_page not in negative_labels:
                    negative_labels.append(auto_page)

        # 예측 횟수 카운트
        if predicted:
            _ensure(predicted)
            stats[predicted]["seen"] += 1
            # 해당 prediction 에 대한 모델 피드백
            if model_feedback == "thumbs_up":
                stats[predicted]["thumbs_up"] += 1
            elif model_feedback == "thumbs_down":
                stats[predicted]["thumbs_down"] += 1

        # positive_labels: 실제 정답 page_key  (edit_saved, corrected_here, thumbs_up fallback)
        for pk in positive_labels:
            pk = pk.strip()
            _ensure(pk)
            stats[pk]["positive_label"] += 1

        # negative_labels: 추천이 틀린 page_key  (used_other_page + 실제 페이지 다름)
        for pk in negative_labels:
            pk = pk.strip()
            _ensure(pk)
            stats[pk]["negative_label"] += 1

    # 수동 라벨 변경 이력(before→after)을 추가 학습 신호로 반영
    for rev in CustomerRequestManualLabelRevision.objects.all().iterator(chunk_size=500):
        before_page = (rev.before_page_key or "").strip()
        after_page = (rev.after_page_key or "").strip()
        if before_page and before_page != after_page:
            _ensure(before_page)
            stats[before_page]["negative_label"] += 1
        if after_page and after_page != before_page:
            _ensure(after_page)
            stats[after_page]["positive_label"] += 1

    # score_boost 계산 및 upsert
    updated = 0
    for page_key, st in stats.items():
        positives = st["positive_label"] + st["thumbs_up"]
        negatives = st["negative_label"] + st["thumbs_down"]
        total_feedback = positives + negatives

        if total_feedback == 0:
            boost = 0.0
        else:
            # 순 양성 비율 ([-1, 1])
            raw = (positives - negatives) / total_feedback
            # 샘플 부족 시 감쇠: _MIN_EVIDENCE 개 이상이면 풀 반영
            confidence_weight = min(total_feedback / _MIN_EVIDENCE, 1.0)
            boost = round(raw * confidence_weight, 4)

        PageKeyFeedbackScore.objects.update_or_create(
            page_key=page_key,
            defaults={
                "thumbs_up_count": st["thumbs_up"],
                "thumbs_down_count": st["thumbs_down"],
                "positive_label_count": st["positive_label"],
                "negative_label_count": st["negative_label"],
                "total_seen": st["seen"],
                "score_boost": boost,
            },
        )
        updated += 1

    invalidate_feedback_score_cache()
    logger.info("rebuild_feedback_scores: updated %d page_key scores", updated)
    return {"updated": updated, "page_keys": list(stats.keys())}


def get_feedback_score_boosts() -> Dict[str, float]:
    """
    {page_key: score_boost} 딕셔너리를 반환한다.
    캐시에 있으면 캐시에서, 없으면 DB 에서 조회 후 캐싱한다.
    """
    try:
        from django.core.cache import cache
        cached = cache.get(_CACHE_KEY)
        if cached is not None:
            return cached
    except Exception:
        cached = None

    try:
        from .models import PageKeyFeedbackScore
        boosts = {
            row.page_key: row.score_boost
            for row in PageKeyFeedbackScore.objects.all()
            if row.score_boost != 0.0
        }
    except Exception as e:
        logger.warning("get_feedback_score_boosts: DB error: %s", e)
        return {}

    try:
        from django.core.cache import cache
        cache.set(_CACHE_KEY, boosts, timeout=_CACHE_TTL)
    except Exception:
        pass

    return boosts


def invalidate_feedback_score_cache() -> None:
    """피드백 점수 캐시를 무효화한다. 다음 요청 시 DB 에서 재조회된다."""
    try:
        from django.core.cache import cache
        cache.delete(_CACHE_KEY)
    except Exception:
        pass


def export_learning_dataset(path: str, *, min_quality: str = "medium") -> Dict[str, Any]:
    """
    학습 요약 데이터를 JSON 파일로 export 한다.

    Args:
        path: 출력 파일 경로
        min_quality: weak|medium|strong (기본 medium)

    Returns:
        {"path": path, "count": n}
    """
    from .models import CustomerRequestLearningSummary

    q = CustomerRequestLearningSummary.objects.all()
    if min_quality == "strong":
        q = q.filter(label_quality="strong")
    elif min_quality == "medium":
        q = q.filter(label_quality__in=["strong", "medium"])

    rows = []
    for row in q.iterator(chunk_size=500):
        s = row.summary if isinstance(row.summary, dict) else {}
        manual_page = (getattr(row, "manual_confirmed_page_key", "") or "").strip()
        auto_positive_labels = s.get("positive_labels") or []
        effective_positive_labels = [manual_page] if manual_page else (s.get("positive_labels") or [])
        revisions_payload = []
        try:
            revisions = row.manual_label_revisions.all().order_by("changed_at")
            for rev in revisions:
                revisions_payload.append({
                    "before_intent": (rev.before_intent or "").strip(),
                    "after_intent": (rev.after_intent or "").strip(),
                    "before_page_key": (rev.before_page_key or "").strip(),
                    "after_page_key": (rev.after_page_key or "").strip(),
                    "changed_at": rev.changed_at.isoformat() if rev.changed_at else "",
                })
        except Exception:
            revisions_payload = []
        rows.append(
            {
                "request_id": row.request_id,
                "label_quality": row.label_quality,
                "label_source": row.label_source if hasattr(row, "label_source") else "auto",
                "user_message": s.get("user_message"),
                "predicted_primary_page": s.get("predicted_primary_page"),
                "auto_positive_labels": auto_positive_labels,
                "positive_labels": effective_positive_labels,
                "negative_labels": s.get("negative_labels") or [],
                "actual_edit_page": s.get("actual_edit_page"),
                "model_feedback_value": s.get("model_feedback_value"),
                "recommendation_failure": bool(s.get("recommendation_failure")),
                "manual_confirmed_intent": (getattr(row, "manual_confirmed_intent", "") or "").strip(),
                "manual_confirmed_page_key": manual_page,
                "manual_label_notes": (getattr(row, "manual_label_notes", "") or "").strip(),
                "manual_label_revisions": revisions_payload,
            }
        )

    with open(path, "w", encoding="utf-8") as fp:
        json.dump(rows, fp, ensure_ascii=False, indent=2)

    logger.info("export_learning_dataset: wrote %d rows to %s", len(rows), path)
    return {"path": path, "count": len(rows)}
