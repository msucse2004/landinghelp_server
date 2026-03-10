"""
공통 고객 요청 LLM 분석 서비스.

분류 파이프라인 호출 순서:  Heuristic → Ollama(로컬) → Gemini(escalation)
- LLM 출력: 구조화된 JSON만 (intent, recommended_action, execution_mode 등).
- 엄격한 JSON 검증 및 confidence/검증 실패 시 fallback (HUMAN_REVIEW_REQUIRED 또는 REPLY_ONLY).
- LLM은 상태 변경/파괴적 액션 실행 금지. 분류·추천·응답 초안 생성만 수행.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, Optional, Tuple

from customer_request_policy import (
    ExecutionMode,
    HumanReviewTarget,
    Intent,
    PolicyResult,
    RecommendedAction,
)

logger = logging.getLogger(__name__)

_cached_sections = None


def _get_survey_section_list():
    """고객 노출 설문 섹션 (id, title) 목록. DB 조회 1회 후 캐싱."""
    global _cached_sections
    if _cached_sections is not None:
        return _cached_sections
    try:
        from survey.models import SurveySection
        _cached_sections = list(
            SurveySection.objects.filter(is_active=True, is_internal=False)
            .order_by("display_order")
            .values_list("id", "title")
        )
    except Exception:
        _cached_sections = []
    return _cached_sections


REQUIRED_LLM_KEYS = frozenset({
    "intent",
    "recommended_action",
    "execution_mode",
    "confidence",
    "human_review_target",
    "customer_summary",
    "internal_summary",
    "target_survey_section_ids",
})

VALID_INTENTS = frozenset(i.value for i in Intent)
VALID_RECOMMENDED_ACTIONS = frozenset(a.value for a in RecommendedAction)
VALID_EXECUTION_MODES = frozenset(m.value for m in ExecutionMode)
VALID_HUMAN_REVIEW_TARGETS = frozenset(t.value for t in HumanReviewTarget)

DEFAULT_CONFIDENCE_THRESHOLD = 0.7

# ---------------------------------------------------------------------------
# 개별 어댑터 팩토리 (분류 파이프라인 전용)
# ---------------------------------------------------------------------------

_ollama_singleton: Optional[object] = None
_gemini_singleton: Optional[object] = None


def get_ollama_adapter():
    """Ollama 어댑터 단독 인스턴스. 연결 불가 시 None."""
    global _ollama_singleton
    if _ollama_singleton is not None:
        return _ollama_singleton
    try:
        from ai_agent.llm_ollama import OllamaAdapter
        _ollama_singleton = OllamaAdapter()
        return _ollama_singleton
    except Exception:
        return None


def get_gemini_adapter():
    """Gemini 어댑터 단독 인스턴스. API key 미설정 시 None."""
    global _gemini_singleton
    if _gemini_singleton is not None:
        return _gemini_singleton
    try:
        from django.conf import settings
        if not getattr(settings, "GEMINI_API_KEY", ""):
            return None
        from ai_agent.llm_gemini import GeminiAdapter
        _gemini_singleton = GeminiAdapter()
        return _gemini_singleton
    except Exception:
        return None


def _model_name_to_source(model_name: str) -> str:
    """default_llm_adapter가 반환하는 model_name을 AnalysisSource 값으로 매핑."""
    mn = (model_name or "").lower()
    if "gemini" in mn:
        return "gemini"
    if "ollama" in mn:
        return "ollama"
    if mn == "stub":
        return "stub"
    if mn in ("ai_agent", "ai_agent_uncertain"):
        return "gemini"
    return "llm"


# ---------------------------------------------------------------------------
# Compact prompt (토큰 절약형 - Ollama용)
# ---------------------------------------------------------------------------

_COMPACT_SYSTEM = """고객 메시지 분류기. JSON만 출력.
필드: intent, recommended_action, execution_mode, confidence(0~1), human_review_target, customer_summary, internal_summary, target_survey_section_ids(배열)
intent: SURVEY_REOPEN_REQUEST|SURVEY_RESUME_REQUEST|QUOTE_RESEND_REQUEST|QUOTE_ITEM_CHANGE_REQUEST|SCHEDULE_CHANGE_REQUEST|AGENT_CHANGE_REQUEST|PRICING_NEGOTIATION_REQUEST|GENERAL_QUESTION|STATUS_CHECK|UNSUPPORTED_REQUEST
recommended_action: OFFER_SURVEY_REOPEN|OFFER_SURVEY_RESUME|OFFER_QUOTE_RESEND|OFFER_QUOTE_REVISION_REQUEST|ROUTE_TO_ADMIN_REVIEW|ROUTE_TO_AGENT_REVIEW|ROUTE_TO_ADMIN_THEN_AGENT|REPLY_WITH_INFORMATION|REPLY_WITH_STATUS
execution_mode: AUTO_CONFIRMABLE(설문재개/이어쓰기/견적재발송만)|HUMAN_REVIEW_REQUIRED(일정/가격/agent변경/고위험)|REPLY_ONLY
human_review_target: admin|agent|admin_then_agent|none
규칙: 일정/가격/agent변경은 반드시 HUMAN_REVIEW_REQUIRED. 모호하면 confidence<0.5, HUMAN_REVIEW_REQUIRED.
target_survey_section_ids: 설문 수정 관련이면 관련 섹션 ID 정수 배열, 아니면 [].
JSON만 출력. 설명 금지."""


def build_compact_prompt(text: str, context: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """Ollama용 토큰 절약형 프롬프트. 시스템 ~200토큰."""
    user_msg = (text or "").strip()
    if context:
        ctx_str = json.dumps(context, ensure_ascii=False)[:500]
        user_msg = f"ctx:{ctx_str}\nmsg:{user_msg}"
    else:
        user_msg = f"msg:{user_msg}"
    user_msg += "\nJSON:"
    return _COMPACT_SYSTEM, user_msg


# ---------------------------------------------------------------------------
# Full prompt (Gemini용 - 세션 목록 포함)
# ---------------------------------------------------------------------------


def build_prompt(text: str, context: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """
    Gemini용 full 프롬프트. 설문 섹션 목록·예시·안전 규칙 포함.
    """
    ctx = context or {}
    system = """고객 메시지를 분류하고 액션을 추천하는 분류기. JSON만 출력.

출력 JSON (모두 필수):
- intent: SURVEY_REOPEN_REQUEST|SURVEY_RESUME_REQUEST|QUOTE_RESEND_REQUEST|QUOTE_ITEM_CHANGE_REQUEST|SCHEDULE_CHANGE_REQUEST|AGENT_CHANGE_REQUEST|PRICING_NEGOTIATION_REQUEST|GENERAL_QUESTION|STATUS_CHECK|UNSUPPORTED_REQUEST
- recommended_action: OFFER_SURVEY_REOPEN|OFFER_SURVEY_RESUME|OFFER_QUOTE_RESEND|OFFER_QUOTE_REVISION_REQUEST|ROUTE_TO_ADMIN_REVIEW|ROUTE_TO_AGENT_REVIEW|ROUTE_TO_ADMIN_THEN_AGENT|REPLY_WITH_INFORMATION|REPLY_WITH_STATUS
- execution_mode: AUTO_CONFIRMABLE|HUMAN_REVIEW_REQUIRED|REPLY_ONLY
- confidence: 0.0~1.0
- human_review_target: admin|agent|admin_then_agent|none
- customer_summary: 고객 안내 1~2문장
- internal_summary: 내부 한 줄 요약
- target_survey_section_ids: 수정 대상 설문 섹션 ID 정수 배열 (무관하면 [])

안전 규칙:
- 일정/가격/agent 변경 → HUMAN_REVIEW_REQUIRED
- 설문 재개/이어쓰기/견적 재발송만 AUTO_CONFIRMABLE 허용
- 모호 → confidence<0.5, HUMAN_REVIEW_REQUIRED

예시: "설문 수정하고 싶어요"→SURVEY_REOPEN_REQUEST,OFFER_SURVEY_REOPEN,AUTO_CONFIRMABLE
"이사 날짜 변경"→SCHEDULE_CHANGE_REQUEST,ROUTE_TO_AGENT_REVIEW,HUMAN_REVIEW_REQUIRED
"견적서 다시"→QUOTE_RESEND_REQUEST,OFFER_QUOTE_RESEND,AUTO_CONFIRMABLE
"가격 조정"→PRICING_NEGOTIATION_REQUEST,ROUTE_TO_ADMIN_REVIEW,HUMAN_REVIEW_REQUIRED
"""

    section_list = _get_survey_section_list()
    if section_list:
        system += "\n설문 섹션 (id:제목):\n"
        for sid, title in section_list:
            system += f"- {sid}:{title}\n"

    user = (text or "").strip()
    if ctx:
        user = json.dumps(ctx, ensure_ascii=False)[:1000] + "\n" + user
    user += "\nJSON만 출력:"

    return system, user


def parse_llm_output(raw: str) -> Dict[str, Any]:
    """LLM 원시 출력에서 JSON 객체 추출. 마크다운 코드블록 제거 후 파싱."""
    if not raw or not isinstance(raw, str):
        return {}
    text = raw.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        text = m.group(1).strip()
    # 블록 없으면 전체를 JSON으로 시도
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def validate_llm_output(data: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    엄격한 JSON 검증.
    반환: (검증된 dict, None) 또는 (None, error_message).
    """
    if not isinstance(data, dict):
        return None, "output is not a dict"

    for key in REQUIRED_LLM_KEYS:
        if key not in data:
            return None, f"missing key: {key}"

    intent = data.get("intent")
    if intent not in VALID_INTENTS:
        return None, f"invalid intent: {intent}"

    rec = data.get("recommended_action")
    if rec not in VALID_RECOMMENDED_ACTIONS:
        return None, f"invalid recommended_action: {rec}"

    mode = data.get("execution_mode")
    if mode not in VALID_EXECUTION_MODES:
        return None, f"invalid execution_mode: {mode}"

    try:
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        return None, "confidence must be a number"
    if not (0 <= confidence <= 1):
        return None, "confidence must be between 0 and 1"

    target = data.get("human_review_target")
    if target not in VALID_HUMAN_REVIEW_TARGETS:
        return None, f"invalid human_review_target: {target}"

    customer_summary = data.get("customer_summary")
    if customer_summary is not None and not isinstance(customer_summary, str):
        customer_summary = str(customer_summary)
    data = {**data, "customer_summary": (customer_summary or "").strip()[:2000]}

    internal_summary = data.get("internal_summary")
    if internal_summary is not None and not isinstance(internal_summary, str):
        internal_summary = str(internal_summary)
    data = {**data, "internal_summary": (internal_summary or "").strip()[:1000]}

    section_ids = data.get("target_survey_section_ids")
    if section_ids is None:
        section_ids = []
    if not isinstance(section_ids, list):
        section_ids = []
    section_ids = [int(s) for s in section_ids if isinstance(s, (int, float, str)) and str(s).isdigit()]
    data = {**data, "target_survey_section_ids": section_ids}

    return data, None


def apply_confidence_fallback(
    data: Dict[str, Any],
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> Dict[str, Any]:
    """
    confidence가 threshold 미만이면 HUMAN_REVIEW_REQUIRED 또는 REPLY_ONLY로 강등.
    AUTO_CONFIRMABLE는 유지하지 않고, human_review_target을 admin으로 올려 수동 검토 유도.
    """
    confidence = float(data.get("confidence", 0))
    if confidence >= threshold:
        return data

    mode = data.get("execution_mode")
    intent = data.get("intent", "")

    # 이미 HUMAN_REVIEW_REQUIRED / REPLY_ONLY면 유지, target만 보정
    if mode == ExecutionMode.REPLY_ONLY.value:
        data = {**data, "human_review_target": HumanReviewTarget.none.value}
        return data

    if mode == ExecutionMode.AUTO_CONFIRMABLE.value:
        # 강등: 자동 실행 후보에서 제외
        data = {
            **data,
            "execution_mode": ExecutionMode.HUMAN_REVIEW_REQUIRED.value,
            "human_review_target": HumanReviewTarget.admin.value,
            "recommended_action": _downgrade_recommended_action(data.get("recommended_action")),
            "customer_summary": (data.get("customer_summary") or "").strip()
            or "요청 내용을 확인했습니다. 검토 후 안내드리겠습니다.",
            "internal_summary": (data.get("internal_summary") or "").strip()
            or f"low_confidence({confidence}) fallback to human review",
        }
        return data

    # 이미 HUMAN_REVIEW_REQUIRED
    if data.get("human_review_target") == HumanReviewTarget.none.value:
        data = {**data, "human_review_target": HumanReviewTarget.admin.value}
    return data


def _downgrade_recommended_action(action: Optional[str]) -> str:
    """AUTO_CONFIRMABLE 액션을 강등 시 수동 검토 쪽으로 매핑. 정책 테이블 기반."""
    if not action:
        return RecommendedAction.ROUTE_TO_ADMIN_REVIEW.value
    from customer_request_policy import ACTION_CODE_POLICY
    offer_actions = {
        e.recommended_action.value
        for e in ACTION_CODE_POLICY.values()
        if e.risk_level.value == "LOW"
    }
    if action in offer_actions:
        return RecommendedAction.ROUTE_TO_ADMIN_REVIEW.value
    if action == RecommendedAction.OFFER_QUOTE_REVISION_REQUEST.value:
        return RecommendedAction.ROUTE_TO_ADMIN_REVIEW.value
    return action


def _data_to_policy_result(data: Dict[str, Any], *, source: str = "llm") -> PolicyResult:
    """검증·폴백까지 적용된 dict를 PolicyResult로 변환."""
    intent = Intent(str(data["intent"]))
    action = RecommendedAction(str(data["recommended_action"]))
    mode = ExecutionMode(str(data["execution_mode"]))
    target = HumanReviewTarget(str(data["human_review_target"]))
    confidence = max(0.0, min(1.0, float(data["confidence"])))
    customer_summary = (data.get("customer_summary") or "").strip() or "요청을 확인했습니다. 검토 후 안내드리겠습니다."
    internal_summary = (data.get("internal_summary") or "").strip() or "llm classification"
    should_offer = mode == ExecutionMode.AUTO_CONFIRMABLE.value and confidence >= DEFAULT_CONFIDENCE_THRESHOLD

    section_ids = tuple(data.get("target_survey_section_ids") or [])

    return PolicyResult(
        detected_intent=intent,
        recommended_action=action,
        execution_mode=mode,
        confidence=confidence,
        human_review_target=target,
        customer_facing_summary=customer_summary,
        internal_reasoning_summary=internal_summary,
        should_create_action_offer=should_offer,
        target_section_ids=section_ids,
        source=source,
    )


# ---------------------------------------------------------------------------
# 개별 LLM 호출 (분류 파이프라인에서 직접 사용)
# ---------------------------------------------------------------------------


def call_ollama_classify(
    text: str,
    context: Optional[Dict[str, Any]] = None,
) -> Optional[PolicyResult]:
    """Ollama(로컬)에 compact prompt로 분류 요청. 실패 시 None."""
    adapter = get_ollama_adapter()
    if not adapter:
        logger.info("call_ollama_classify: adapter not available")
        return None
    return _call_single_adapter(adapter, text, context, source="ollama", compact=True)


def call_gemini_classify(
    text: str,
    context: Optional[Dict[str, Any]] = None,
) -> Optional[PolicyResult]:
    """Gemini에 full prompt로 분류 요청 (escalation 전용). 실패 시 None."""
    adapter = get_gemini_adapter()
    if not adapter:
        logger.info("call_gemini_classify: adapter not available")
        return None
    return _call_single_adapter(adapter, text, context, source="gemini", compact=False)


def _call_single_adapter(
    adapter: Any,
    text: str,
    context: Optional[Dict[str, Any]],
    *,
    source: str,
    compact: bool,
    max_tokens: int = 400,
) -> Optional[PolicyResult]:
    """단일 어댑터로 분류 호출. 검증·폴백 적용 후 PolicyResult 반환."""
    try:
        if compact:
            system, user = build_compact_prompt(text, context)
        else:
            system, user = build_prompt(text, context)
        raw, uncertainty = adapter.generate(
            system_prompt=system,
            user_prompt=user,
            language="ko",
            max_tokens=max_tokens,
        )
    except Exception as e:
        logger.warning("_call_single_adapter(%s) error: %s", source, e)
        return None

    if not raw or not isinstance(raw, str):
        logger.info("_call_single_adapter(%s): empty response", source)
        return None

    data = parse_llm_output(raw)
    validated, err = validate_llm_output(data)
    if err or not validated:
        logger.info("_call_single_adapter(%s): validation failed (%s)", source, err)
        return None

    try:
        validated = apply_confidence_fallback(validated, DEFAULT_CONFIDENCE_THRESHOLD)
    except Exception:
        validated = {**validated, "execution_mode": ExecutionMode.HUMAN_REVIEW_REQUIRED.value}

    try:
        result = _data_to_policy_result(validated, source=source)
        logger.info(
            "_call_single_adapter(%s): intent=%s mode=%s conf=%.2f",
            source, result.detected_intent, result.execution_mode, result.confidence,
        )
        return result
    except Exception as e:
        logger.warning("_call_single_adapter(%s) _data_to_policy_result error: %s", source, e)
        return None


# ---------------------------------------------------------------------------
# 레거시 호환: analyze_customer_message_llm (기존 호출자용)
# ---------------------------------------------------------------------------


def analyze_customer_message_llm(
    text: str,
    context: Optional[Dict[str, Any]] = None,
    llm_adapter: Optional[Callable[[str, str], Tuple[str, str]]] = None,
    confidence_threshold: Optional[float] = None,
) -> Optional[PolicyResult]:
    """
    레거시 호환. llm_adapter가 지정되면 기존 방식(ChainAdapter), 아니면 새 파이프라인 위임.
    """
    if llm_adapter:
        return _legacy_llm_call(text, context, llm_adapter, confidence_threshold)
    result = call_ollama_classify(text, context)
    if result is not None:
        return result
    result = call_gemini_classify(text, context)
    if result is not None:
        return result
    return None


def _legacy_llm_call(
    text: str,
    context: Optional[Dict[str, Any]],
    llm_adapter: Callable[[str, str], Tuple[str, str]],
    confidence_threshold: Optional[float],
) -> Optional[PolicyResult]:
    """기존 llm_adapter 콜백을 사용하는 레거시 경로."""
    threshold = confidence_threshold if confidence_threshold is not None else DEFAULT_CONFIDENCE_THRESHOLD
    try:
        system, user = build_prompt(text, context)
        raw_response, model_name = llm_adapter(system, user)
    except Exception as e:
        logger.warning("legacy LLM adapter error: %s", e, exc_info=True)
        return None

    if not raw_response or not isinstance(raw_response, str):
        return None

    data = parse_llm_output(raw_response)
    validated, err = validate_llm_output(data)
    if err or not validated:
        return None

    try:
        validated = apply_confidence_fallback(validated, threshold)
    except Exception:
        validated = {**validated, "execution_mode": ExecutionMode.HUMAN_REVIEW_REQUIRED.value}

    try:
        llm_source = _model_name_to_source(model_name)
        return _data_to_policy_result(validated, source=llm_source)
    except Exception:
        return None
