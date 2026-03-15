"""
견적 변경 요청 LLM 해석 서비스.

- 고객 자유 텍스트를 공통 정책 스키마(intent / recommended_action / execution_mode 등)로 분석.
- DB 상태 변경 없음. 분류·추천·요약만 수행. 실행은 Admin 승인 후 별도 플로우.
- JSON 검증·confidence 폴백은 customer_request_llm 공통 모듈 사용.
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from django.conf import settings

from customer_request_llm import (
    apply_confidence_fallback,
    build_prompt,
    parse_llm_output,
    validate_llm_output,
)

logger = logging.getLogger(__name__)

# QuoteChangeAnalysis.DetectedIntent 호환용 레거시 상수 (기존 코드 참조용)
INTENT_QUOTE_ITEM_CHANGE = "QUOTE_ITEM_CHANGE_REQUEST"
INTENT_SURVEY_REOPEN = "SURVEY_REOPEN_REQUEST"
INTENT_GENERAL_QUESTION = "GENERAL_QUESTION"
INTENT_UNSUPPORTED = "UNSUPPORTED_REQUEST"
INTENT_URGENT_ADMIN = "URGENT_ADMIN_REVIEW"

# 공통 스키마 intent → QuoteChangeAnalysis.DetectedIntent (5종) 매핑
_INTENT_TO_LEGACY: Dict[str, str] = {
    "SURVEY_REOPEN_REQUEST": INTENT_SURVEY_REOPEN,
    "SURVEY_RESUME_REQUEST": INTENT_SURVEY_REOPEN,
    "QUOTE_RESEND_REQUEST": INTENT_QUOTE_ITEM_CHANGE,
    "QUOTE_ITEM_CHANGE_REQUEST": INTENT_QUOTE_ITEM_CHANGE,
    "SCHEDULE_CHANGE_REQUEST": INTENT_URGENT_ADMIN,
    "AGENT_CHANGE_REQUEST": INTENT_URGENT_ADMIN,
    "PRICING_NEGOTIATION_REQUEST": INTENT_URGENT_ADMIN,
    "GENERAL_QUESTION": INTENT_GENERAL_QUESTION,
    "STATUS_CHECK": INTENT_GENERAL_QUESTION,
    "UNSUPPORTED_REQUEST": INTENT_UNSUPPORTED,
}


def _map_intent_to_legacy(intent: str) -> str:
    """공통 taxonomy intent → QuoteChangeAnalysis.DetectedIntent 값."""
    return _INTENT_TO_LEGACY.get(intent, INTENT_URGENT_ADMIN)


def get_quote_change_llm_adapter() -> Callable[[str, str], Tuple[str, str]]:
    """
    LLM 어댑터 반환. (system_prompt, user_prompt) -> (raw_response_text, model_name).
    테스트/목에서 교체 가능하도록 설정 또는 기본 stub 사용.
    """
    adapter = getattr(settings, "QUOTE_CHANGE_LLM_ADAPTER", None)
    if adapter is not None and adapter != "stub":
        try:
            if isinstance(adapter, str) and "." in adapter:
                from django.utils.module_loading import import_string

                impl = import_string(adapter)
                if callable(impl) and not isinstance(impl, type):
                    return impl
                if isinstance(impl, type):
                    inst = impl()
                    if hasattr(inst, "generate_quote_change_analysis"):
                        return getattr(inst, "generate_quote_change_analysis")
                    if callable(inst):
                        return inst
                    if hasattr(impl, "generate_quote_change_analysis") and callable(
                        getattr(impl, "generate_quote_change_analysis")
                    ):
                        return getattr(impl, "generate_quote_change_analysis")
                if (
                    hasattr(impl, "generate_quote_change_analysis")
                    and callable(getattr(impl, "generate_quote_change_analysis"))
                ):
                    return getattr(impl, "generate_quote_change_analysis")
            if callable(adapter):
                return adapter
        except Exception as e:
            logger.warning("QUOTE_CHANGE_LLM_ADAPTER load failed: %s", e, exc_info=True)
    return _stub_llm_adapter


def _default_stub_json() -> str:
    """LLM 미연동 시 공통 스키마로 수동 검토 권장 JSON 반환."""
    from customer_request_policy import (
        ExecutionMode,
        HumanReviewTarget,
        Intent,
        RecommendedAction,
    )
    import json

    return json.dumps(
        {
            "intent": Intent.UNSUPPORTED_REQUEST.value,
            "recommended_action": RecommendedAction.ROUTE_TO_ADMIN_REVIEW.value,
            "execution_mode": ExecutionMode.HUMAN_REVIEW_REQUIRED.value,
            "confidence": 0.0,
            "human_review_target": HumanReviewTarget.admin.value,
            "customer_summary": "요청을 확인했습니다. 검토 후 안내드리겠습니다.",
            "internal_summary": "LLM 미연동(stub). Admin이 메시지를 확인해 주세요.",
            "target_survey_section_ids": [],
        },
        ensure_ascii=False,
    )


def _stub_llm_adapter(system_prompt: str, user_prompt: str) -> Tuple[str, str]:
    """LLM 미연동 시 공통 스키마로 수동 검토 권장 JSON 반환."""
    del system_prompt, user_prompt
    return _default_stub_json(), "stub"


# ---------------------------------------------------------------------------
# 서비스 코드 매핑 (프롬프트·컨텍스트용)
# ---------------------------------------------------------------------------


def get_service_codes_for_prompt() -> List[Tuple[str, str]]:
    """
    현재 활성 SettlementService 목록을 (code, name) 리스트로 반환.
    LLM 컨텍스트에 포함해 서비스 이름/별칭 매핑 참고용.
    """
    from .models import SettlementService

    qs = SettlementService.objects.filter(is_active=True).order_by("category", "name")
    return [(s.code or "", s.name or "") for s in qs if (s.code or s.name)]


def resolve_service_code_from_text(
    text: str,
    candidates: Optional[List[Tuple[str, str]]] = None,
) -> Optional[str]:
    """텍스트(서비스명/별칭)를 service_code로 추정. 매칭 없으면 None."""
    if not (text or "").strip():
        return None
    text = (text or "").strip().lower()
    if candidates is None:
        candidates = get_service_codes_for_prompt()
    for code, name in candidates:
        if not code and not name:
            continue
        if name and text in (name or "").lower():
            return code or None
        if code and text in (code or "").lower():
            return code
    return None


# ---------------------------------------------------------------------------
# 프롬프트 생성 (공통 스키마 + 견적 컨텍스트)
# ---------------------------------------------------------------------------


def _build_quote_context(change_request) -> Dict[str, Any]:
    """QuoteChangeRequest에서 공통 build_prompt용 context dict 생성."""
    ctx: Dict[str, Any] = {}
    quote_items_summary: List[str] = []
    try:
        quote = getattr(change_request, "quote", None)
        if quote and getattr(quote, "items", None):
            for it in (quote.items or [])[:30]:
                if isinstance(it, dict):
                    code = it.get("code") or ""
                    label = it.get("label") or ""
                    quote_items_summary.append(f"- {code}: {label}")
    except Exception:
        quote_items_summary = ["- (로드 실패)"]
    ctx["quote_items"] = quote_items_summary

    service_candidates = get_service_codes_for_prompt()
    ctx["service_codes"] = [f"{code}: {name}" for code, name in (service_candidates or [])[:80]]
    return ctx


def build_quote_change_analysis_prompt(change_request) -> Tuple[str, str]:
    """
    견적 변경 요청용 system/user 프롬프트 생성.
    공통 스키마(intent, recommended_action, execution_mode, customer_summary, internal_summary 등)로 응답하도록 함.
    """
    customer_message = (getattr(change_request, "customer_message", None) or "").strip()
    if not customer_message:
        customer_message = "(고객 메시지 없음)"
    context = _build_quote_context(change_request)
    return build_prompt(customer_message, context)


# ---------------------------------------------------------------------------
# 메인: 분석 실행 → QuoteChangeAnalysis 생성만 (상태 변경 없음)
# ---------------------------------------------------------------------------


def analyze_quote_change_request(
    change_request,
    llm_adapter: Optional[Callable[[str, str], Tuple[str, str]]] = None,
) -> Optional["QuoteChangeAnalysis"]:
    """
    고객 자유 텍스트를 LLM으로 해석하여 QuoteChangeAnalysis 한 건 생성.
    - 공통 스키마 검증·confidence 폴백 적용. 실패 시 수동 검토용 레거시 분석 저장.
    - change_request.status 등 다른 상태는 변경하지 않음. LLM은 분류/추천만 수행.
    """
    from .models import QuoteChangeAnalysis, QuoteChangeRequest

    if not isinstance(change_request, QuoteChangeRequest):
        logger.warning("analyze_quote_change_request: invalid change_request type")
        return None

    if not change_request.can_run_llm_analysis():
        logger.info("analyze_quote_change_request: can_run_llm_analysis=False, skip")
        return None

    raw_customer_message = (change_request.customer_message or "").strip()
    if not raw_customer_message:
        raw_customer_message = "(고객 메시지 없음)"

    system_prompt, user_prompt = build_quote_change_analysis_prompt(change_request)
    adapter = llm_adapter or get_quote_change_llm_adapter()

    try:
        raw_response, model_name = adapter(system_prompt, user_prompt)
    except Exception as e:
        logger.warning("Quote change LLM adapter error: %s", e, exc_info=True)
        raw_response = None
        model_name = "error_fallback"

    raw_response = raw_response or ""
    data = parse_llm_output(raw_response)
    validated, err = validate_llm_output(data)

    confidence_threshold = getattr(settings, "QUOTE_CHANGE_LLM_CONFIDENCE_THRESHOLD", 0.7)
    try:
        confidence_threshold = float(confidence_threshold)
    except (TypeError, ValueError):
        confidence_threshold = 0.7
    confidence_threshold = max(0.0, min(1.0, confidence_threshold))

    if err or not validated:
        validated = {
            "intent": "UNSUPPORTED_REQUEST",
            "recommended_action": "ROUTE_TO_ADMIN_REVIEW",
            "execution_mode": "HUMAN_REVIEW_REQUIRED",
            "confidence": 0.0,
            "human_review_target": "admin",
            "customer_summary": "자동 분류할 수 없습니다. Admin이 메시지를 확인해 주세요.",
            "internal_summary": f"검증 실패: {err or 'parse error'}. Admin이 고객 메시지를 읽고 설문 재개 또는 견적 수정 중 선택하세요.",
            "target_survey_section_ids": [],
        }
        logger.info(
            "analyze_quote_change_request: validation failed (%s), using fallback",
            err,
        )

    try:
        validated = apply_confidence_fallback(validated, confidence_threshold)
    except Exception as e:
        logger.warning("apply_confidence_fallback error: %s", e, exc_info=True)
        validated = {**validated, "execution_mode": "HUMAN_REVIEW_REQUIRED", "human_review_target": "admin"}

    intent = validated.get("intent", "UNSUPPORTED_REQUEST")
    legacy_intent = _map_intent_to_legacy(intent)
    confidence = max(0.0, min(1.0, float(validated.get("confidence", 0))))
    customer_summary = (validated.get("customer_summary") or "").strip()[:2000]
    internal_summary = (validated.get("internal_summary") or "").strip()[:1000]
    execution_mode = validated.get("execution_mode", "HUMAN_REVIEW_REQUIRED")
    human_review_target = validated.get("human_review_target", "admin")
    recommended_action = validated.get("recommended_action", "ROUTE_TO_ADMIN_REVIEW")

    requires_admin = execution_mode == "HUMAN_REVIEW_REQUIRED" or human_review_target != "none"
    recommended_next_step = internal_summary or "고객 메시지를 확인한 뒤 설문 재개 또는 견적 수정 중 선택하세요."

    # 레거시 호환: extracted_actions (한 항목으로 요약)
    extracted_actions = [
        {
            "action_type": recommended_action,
            "service_code": None,
            "reason": internal_summary[:500],
        }
    ]
    extracted_service_codes: List[str] = []

    raw_llm_output: Dict[str, Any] = {
        "schema": "customer_request_policy_v1",
        "intent": intent,
        "recommended_action": recommended_action,
        "execution_mode": execution_mode,
        "human_review_target": human_review_target,
        "internal_summary": internal_summary,
    }
    if raw_response:
        raw_llm_output["raw_preview"] = (raw_response[:2000] + ("..." if len(raw_response) > 2000 else ""))

    try:
        analysis = QuoteChangeAnalysis(
            change_request=change_request,
            model_name=model_name or "",
            raw_customer_message=raw_customer_message,
            normalized_summary=customer_summary,
            detected_intent=legacy_intent,
            confidence=confidence,
            extracted_actions=extracted_actions,
            extracted_service_codes=extracted_service_codes,
            requires_admin_confirmation=requires_admin,
            recommended_next_step=recommended_next_step[:500],
            raw_llm_output=raw_llm_output,
        )
        analysis.save()
        logger.info(
            "QuoteChangeAnalysis created: request_id=%s intent=%s legacy_intent=%s confidence=%s",
            change_request.id,
            intent,
            legacy_intent,
            confidence,
        )
        return analysis
    except Exception as e:
        logger.exception("QuoteChangeAnalysis save failed: %s", e)
        return None
