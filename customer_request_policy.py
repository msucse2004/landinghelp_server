"""
공통 고객 요청 정책 엔진.

목표:
- LLM은 "분류기 + 제안기"로만 동작 (실행기 아님)
- 뷰는 문자열 비교로 분기하지 않고, 본 모듈을 호출해 정책 결과(의도/액션/실행모드)를 얻는다.
- 새 intent/action 추가 시 ACTION_POLICY_TABLE 에만 항목을 추가하면 모든 하위 로직이 자동 적용.

이 모듈은 Django App에 종속되지 않도록(순수 파이썬) 작성해 messaging/settlement 어디서든 import 가능.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------


class Intent(StrEnum):
    SURVEY_REOPEN_REQUEST = "SURVEY_REOPEN_REQUEST"
    SURVEY_RESUME_REQUEST = "SURVEY_RESUME_REQUEST"
    QUOTE_RESEND_REQUEST = "QUOTE_RESEND_REQUEST"
    QUOTE_ITEM_CHANGE_REQUEST = "QUOTE_ITEM_CHANGE_REQUEST"
    PAYMENT_LINK_RESEND_REQUEST = "PAYMENT_LINK_RESEND_REQUEST"
    SCHEDULE_CHANGE_REQUEST = "SCHEDULE_CHANGE_REQUEST"
    AGENT_CHANGE_REQUEST = "AGENT_CHANGE_REQUEST"
    PRICING_NEGOTIATION_REQUEST = "PRICING_NEGOTIATION_REQUEST"
    REFUND_REQUEST = "REFUND_REQUEST"
    LEGAL_COMPLAINT = "LEGAL_COMPLAINT"
    GENERAL_QUESTION = "GENERAL_QUESTION"
    STATUS_CHECK = "STATUS_CHECK"
    UNSUPPORTED_REQUEST = "UNSUPPORTED_REQUEST"


class RecommendedAction(StrEnum):
    OFFER_SURVEY_REOPEN = "OFFER_SURVEY_REOPEN"
    OFFER_SURVEY_RESUME = "OFFER_SURVEY_RESUME"
    OFFER_QUOTE_RESEND = "OFFER_QUOTE_RESEND"
    OFFER_QUOTE_REVISION_REQUEST = "OFFER_QUOTE_REVISION_REQUEST"
    OFFER_PAYMENT_LINK_RESEND = "OFFER_PAYMENT_LINK_RESEND"
    ROUTE_TO_ADMIN_REVIEW = "ROUTE_TO_ADMIN_REVIEW"
    ROUTE_TO_AGENT_REVIEW = "ROUTE_TO_AGENT_REVIEW"
    ROUTE_TO_ADMIN_THEN_AGENT = "ROUTE_TO_ADMIN_THEN_AGENT"
    REPLY_WITH_INFORMATION = "REPLY_WITH_INFORMATION"
    REPLY_WITH_STATUS = "REPLY_WITH_STATUS"


class ExecutionMode(StrEnum):
    AUTO_CONFIRMABLE = "AUTO_CONFIRMABLE"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    REPLY_ONLY = "REPLY_ONLY"


class HumanReviewTarget(StrEnum):
    admin = "admin"
    agent = "agent"
    admin_then_agent = "admin_then_agent"
    none = "none"


class RiskLevel(StrEnum):
    LOW = "LOW"
    HIGH = "HIGH"
    INFO = "INFO"


@dataclass(frozen=True)
class PolicyResult:
    detected_intent: Intent
    recommended_action: RecommendedAction
    execution_mode: ExecutionMode
    confidence: float
    human_review_target: HumanReviewTarget
    customer_facing_summary: str
    internal_reasoning_summary: str
    should_create_action_offer: bool
    target_section_ids: Tuple[int, ...] = ()
    source: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "detected_intent": str(self.detected_intent),
            "recommended_action": str(self.recommended_action),
            "execution_mode": str(self.execution_mode),
            "confidence": float(self.confidence),
            "human_review_target": str(self.human_review_target),
            "customer_facing_summary": self.customer_facing_summary,
            "internal_reasoning_summary": self.internal_reasoning_summary,
            "should_create_action_offer": bool(self.should_create_action_offer),
            "target_section_ids": list(self.target_section_ids),
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# 정책 테이블 (ACTION_POLICY_TABLE)
#
# 새 intent/action 추가 시 이 테이블에 항목 하나만 추가하면:
#   - 휴리스틱 분류, LLM 결과 매핑, 리스크 판정
#   - 버튼 라벨, 안내 메시지, 성공/실패 메시지
#   - proposal_type, action_code 매핑
# 이 모두 자동으로 적용됨.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionPolicyEntry:
    """
    intent별 정책 정의.

    새 intent/action 추가 시:
    1. Intent enum에 값 추가
    2. 필요 시 RecommendedAction enum에 값 추가
    3. 아래 _POLICY_ENTRIES에 항목 추가
    4. (auto-confirmable인 경우) customer_request_service.py의 _get_action_executors()에 실행 함수 등록
    5. (heuristic 매칭 필요 시) _HEURISTIC_PATTERNS에 regex 추가
    """
    intent: Intent
    risk_level: RiskLevel
    requires_user_confirmation: bool
    allows_direct_execution: bool
    requires_human_review: bool
    execution_mode: ExecutionMode
    human_review_target: HumanReviewTarget
    recommended_action: RecommendedAction
    action_code: str = ""
    proposal_type: str = ""
    proposal_template_key: str = ""
    button_label: str = "진행하기"
    offer_title: str = ""
    guide_message: str = ""
    success_message: str = "요청이 처리되었습니다."
    customer_facing_summary: str = ""


_POLICY_ENTRIES: Tuple[ActionPolicyEntry, ...] = (
    # ── LOW RISK / auto-confirmable ──────────────────────────────────────
    ActionPolicyEntry(
        intent=Intent.SURVEY_REOPEN_REQUEST,
        risk_level=RiskLevel.LOW,
        requires_user_confirmation=True,
        allows_direct_execution=True,
        requires_human_review=False,
        execution_mode=ExecutionMode.AUTO_CONFIRMABLE,
        human_review_target=HumanReviewTarget.none,
        recommended_action=RecommendedAction.OFFER_SURVEY_REOPEN,
        action_code="reopen_survey",
        proposal_type="SURVEY_REOPEN",
        proposal_template_key="survey_reopen",
        button_label="설문 수정하기",
        offer_title="설문 수정",
        guide_message=(
            "서비스를 변경하려면 설문을 다시 수정할 수 있어요.\n"
            "아래 '설문 수정하기' 버튼을 눌러 진행해 주세요.\n"
            "(버튼을 누르기 전에는 변경되지 않습니다.)"
        ),
        success_message="설문이 다시 열렸습니다. '설문 수정하기' 버튼을 눌러 수정을 시작해 주세요.",
        customer_facing_summary="설문을 다시 수정할 수 있도록 열어드릴까요?",
    ),
    ActionPolicyEntry(
        intent=Intent.SURVEY_RESUME_REQUEST,
        risk_level=RiskLevel.LOW,
        requires_user_confirmation=True,
        allows_direct_execution=True,
        requires_human_review=False,
        execution_mode=ExecutionMode.AUTO_CONFIRMABLE,
        human_review_target=HumanReviewTarget.none,
        recommended_action=RecommendedAction.OFFER_SURVEY_RESUME,
        action_code="resume_survey",
        proposal_type="SURVEY_RESUME",
        proposal_template_key="survey_resume",
        button_label="설문 이어쓰기",
        offer_title="설문 이어쓰기",
        guide_message=(
            "이전에 작성 중이던 설문을 이어서 작성할 수 있어요.\n"
            "아래 '설문 이어쓰기' 버튼을 눌러 진행해 주세요."
        ),
        success_message="설문 이어쓰기 링크가 준비되었습니다. '설문 수정하기' 버튼을 눌러 주세요.",
        customer_facing_summary="설문을 이어서 작성할 수 있는 링크를 다시 드릴까요?",
    ),
    ActionPolicyEntry(
        intent=Intent.QUOTE_RESEND_REQUEST,
        risk_level=RiskLevel.LOW,
        requires_user_confirmation=True,
        allows_direct_execution=True,
        requires_human_review=False,
        execution_mode=ExecutionMode.AUTO_CONFIRMABLE,
        human_review_target=HumanReviewTarget.none,
        recommended_action=RecommendedAction.OFFER_QUOTE_RESEND,
        action_code="resend_quote",
        proposal_type="QUOTE_RESEND",
        proposal_template_key="quote_resend",
        button_label="견적서 다시 받기",
        offer_title="견적서 재발송",
        guide_message=(
            "견적서를 다시 보내드릴까요?\n"
            "아래 '견적서 다시 받기' 버튼을 눌러 주세요."
        ),
        success_message="견적서가 다시 발송되었습니다. 메시지함 또는 이메일을 확인해 주세요.",
        customer_facing_summary="견적서를 다시 보내드릴까요?",
    ),
    ActionPolicyEntry(
        intent=Intent.PAYMENT_LINK_RESEND_REQUEST,
        risk_level=RiskLevel.LOW,
        requires_user_confirmation=True,
        allows_direct_execution=True,
        requires_human_review=False,
        execution_mode=ExecutionMode.AUTO_CONFIRMABLE,
        human_review_target=HumanReviewTarget.none,
        recommended_action=RecommendedAction.OFFER_PAYMENT_LINK_RESEND,
        action_code="resend_payment_link",
        proposal_type="PAYMENT_LINK_RESEND",
        proposal_template_key="payment_link_resend",
        button_label="결제 링크 다시 받기",
        offer_title="결제 링크 재발송",
        guide_message=(
            "결제 링크를 다시 보내드릴까요?\n"
            "아래 '결제 링크 다시 받기' 버튼을 눌러 주세요."
        ),
        success_message="결제 링크가 다시 발송되었습니다. 메시지함 또는 이메일을 확인해 주세요.",
        customer_facing_summary="결제 링크를 다시 보내드릴까요?",
    ),

    # ── HIGH RISK / human review ─────────────────────────────────────────
    ActionPolicyEntry(
        intent=Intent.QUOTE_ITEM_CHANGE_REQUEST,
        risk_level=RiskLevel.HIGH,
        requires_user_confirmation=False,
        allows_direct_execution=False,
        requires_human_review=True,
        execution_mode=ExecutionMode.HUMAN_REVIEW_REQUIRED,
        human_review_target=HumanReviewTarget.admin,
        recommended_action=RecommendedAction.ROUTE_TO_ADMIN_REVIEW,
        action_code="open_revision_flow",
        proposal_type="QUOTE_REVISION",
        proposal_template_key="quote_revision",
        button_label="견적 수정 요청",
        offer_title="견적 수정",
        guide_message=(
            "견적 수정 요청을 접수할 수 있어요.\n"
            "아래 '견적 수정 요청' 버튼을 눌러 주세요."
        ),
        success_message="견적 수정 요청이 접수되었습니다. 검토 후 안내드리겠습니다.",
        customer_facing_summary="견적 항목 변경 요청을 접수했습니다. 검토 후 안내드릴게요.",
    ),
    ActionPolicyEntry(
        intent=Intent.SCHEDULE_CHANGE_REQUEST,
        risk_level=RiskLevel.HIGH,
        requires_user_confirmation=False,
        allows_direct_execution=False,
        requires_human_review=True,
        execution_mode=ExecutionMode.HUMAN_REVIEW_REQUIRED,
        human_review_target=HumanReviewTarget.agent,
        recommended_action=RecommendedAction.ROUTE_TO_AGENT_REVIEW,
        customer_facing_summary="일정 변경 요청을 접수했습니다. 담당자가 확인 후 안내드릴게요.",
    ),
    ActionPolicyEntry(
        intent=Intent.AGENT_CHANGE_REQUEST,
        risk_level=RiskLevel.HIGH,
        requires_user_confirmation=False,
        allows_direct_execution=False,
        requires_human_review=True,
        execution_mode=ExecutionMode.HUMAN_REVIEW_REQUIRED,
        human_review_target=HumanReviewTarget.admin_then_agent,
        recommended_action=RecommendedAction.ROUTE_TO_ADMIN_THEN_AGENT,
        customer_facing_summary="담당 Agent 변경 요청을 접수했습니다. 운영자가 확인 후 안내드릴게요.",
    ),
    ActionPolicyEntry(
        intent=Intent.PRICING_NEGOTIATION_REQUEST,
        risk_level=RiskLevel.HIGH,
        requires_user_confirmation=False,
        allows_direct_execution=False,
        requires_human_review=True,
        execution_mode=ExecutionMode.HUMAN_REVIEW_REQUIRED,
        human_review_target=HumanReviewTarget.admin,
        recommended_action=RecommendedAction.ROUTE_TO_ADMIN_REVIEW,
        customer_facing_summary="가격/범위 조정 요청을 접수했습니다. 운영자가 검토 후 안내드릴게요.",
    ),
    ActionPolicyEntry(
        intent=Intent.REFUND_REQUEST,
        risk_level=RiskLevel.HIGH,
        requires_user_confirmation=False,
        allows_direct_execution=False,
        requires_human_review=True,
        execution_mode=ExecutionMode.HUMAN_REVIEW_REQUIRED,
        human_review_target=HumanReviewTarget.admin,
        recommended_action=RecommendedAction.ROUTE_TO_ADMIN_REVIEW,
        customer_facing_summary="환불 요청을 접수했습니다. 운영자가 검토 후 안내드릴게요.",
    ),
    ActionPolicyEntry(
        intent=Intent.LEGAL_COMPLAINT,
        risk_level=RiskLevel.HIGH,
        requires_user_confirmation=False,
        allows_direct_execution=False,
        requires_human_review=True,
        execution_mode=ExecutionMode.HUMAN_REVIEW_REQUIRED,
        human_review_target=HumanReviewTarget.admin,
        recommended_action=RecommendedAction.ROUTE_TO_ADMIN_REVIEW,
        customer_facing_summary="접수되었습니다. 운영자가 확인 후 안내드리겠습니다.",
    ),

    # ── INFO / reply only ────────────────────────────────────────────────
    ActionPolicyEntry(
        intent=Intent.STATUS_CHECK,
        risk_level=RiskLevel.INFO,
        requires_user_confirmation=False,
        allows_direct_execution=False,
        requires_human_review=False,
        execution_mode=ExecutionMode.REPLY_ONLY,
        human_review_target=HumanReviewTarget.none,
        recommended_action=RecommendedAction.REPLY_WITH_STATUS,
        customer_facing_summary="현재 진행 상황을 확인해드릴게요.",
    ),
    ActionPolicyEntry(
        intent=Intent.GENERAL_QUESTION,
        risk_level=RiskLevel.INFO,
        requires_user_confirmation=False,
        allows_direct_execution=False,
        requires_human_review=False,
        execution_mode=ExecutionMode.REPLY_ONLY,
        human_review_target=HumanReviewTarget.none,
        recommended_action=RecommendedAction.REPLY_WITH_INFORMATION,
        customer_facing_summary="문의 내용을 확인했습니다. 필요한 정보를 안내드릴게요.",
    ),
    ActionPolicyEntry(
        intent=Intent.UNSUPPORTED_REQUEST,
        risk_level=RiskLevel.INFO,
        requires_user_confirmation=False,
        allows_direct_execution=False,
        requires_human_review=True,
        execution_mode=ExecutionMode.HUMAN_REVIEW_REQUIRED,
        human_review_target=HumanReviewTarget.admin,
        recommended_action=RecommendedAction.ROUTE_TO_ADMIN_REVIEW,
        customer_facing_summary="요청을 확인했습니다. 검토 후 안내드리겠습니다.",
    ),
)


# ---------------------------------------------------------------------------
# 인덱스 (테이블에서 자동 생성)
# ---------------------------------------------------------------------------

INTENT_POLICY: Dict[Intent, ActionPolicyEntry] = {
    e.intent: e for e in _POLICY_ENTRIES
}

ACTION_CODE_POLICY: Dict[str, ActionPolicyEntry] = {
    e.action_code: e for e in _POLICY_ENTRIES if e.action_code
}

_DEFAULT_ENTRY = INTENT_POLICY[Intent.GENERAL_QUESTION]


# ---------------------------------------------------------------------------
# 조회 헬퍼
# ---------------------------------------------------------------------------


def get_policy_for_intent(intent: Intent) -> ActionPolicyEntry:
    """Intent로 정책 조회. 미등록 intent면 GENERAL_QUESTION 기본값."""
    return INTENT_POLICY.get(intent, _DEFAULT_ENTRY)


def get_policy_for_action_code(code: str) -> Optional[ActionPolicyEntry]:
    """action_code로 정책 조회. 미등록이면 None."""
    return ACTION_CODE_POLICY.get(code)


# ---------------------------------------------------------------------------
# Risk / confidence 게이트 (테이블에서 자동 도출)
# ---------------------------------------------------------------------------

_HIGH_RISK_INTENTS = frozenset(
    e.intent for e in _POLICY_ENTRIES if e.risk_level == RiskLevel.HIGH
)

_LOW_RISK_INTENTS = frozenset(
    e.intent for e in _POLICY_ENTRIES if e.risk_level == RiskLevel.LOW
)

HEURISTIC_ACCEPT_THRESHOLD = 0.65
OLLAMA_ACCEPT_THRESHOLD = 0.7


def is_high_risk_intent(intent: Intent) -> bool:
    return intent in _HIGH_RISK_INTENTS


def is_low_risk_intent(intent: Intent) -> bool:
    return intent in _LOW_RISK_INTENTS


# ---------------------------------------------------------------------------
# LLM adapter (선택)
# ---------------------------------------------------------------------------


LLMAdapter = Callable[[str, str], Tuple[str, str]]


def default_llm_adapter(system_prompt: str, user_prompt: str) -> Tuple[str, str]:
    """ai_agent.llm_adapter를 통해 LLM 호출. 미연동이면 stub 반환."""
    try:
        from ai_agent.llm_adapter import generate
        raw, uncertainty = generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            language="ko",
            max_tokens=800,
        )
        if raw and not uncertainty:
            return raw, "ai_agent"
        if raw:
            return raw, "ai_agent_uncertain"
    except Exception:
        pass
    return (
        json.dumps(
            {
                "intent": Intent.UNSUPPORTED_REQUEST.value,
                "recommended_action": RecommendedAction.ROUTE_TO_ADMIN_REVIEW.value,
                "execution_mode": ExecutionMode.HUMAN_REVIEW_REQUIRED.value,
                "confidence": 0.0,
                "human_review_target": HumanReviewTarget.admin.value,
                "customer_summary": "요청을 확인했습니다. 검토 후 안내드리겠습니다.",
                "internal_summary": "LLM adapter 미설정",
                "target_survey_section_ids": [],
            },
            ensure_ascii=False,
        ),
        "stub",
    )


# ---------------------------------------------------------------------------
# Heuristic classifier — 패턴 테이블
# ---------------------------------------------------------------------------

_RE_SURVEY_RESUME = re.compile(r"(링크|link|resume|이어|계속).*(설문|survey|서베이|form)", re.I)
_RE_SURVEY_REOPEN = re.compile(
    r"(설문|서베이|survey|questionnaire|form).*(수정|편집|다시|재작성|change|edit|revise|reopen)|"
    r"(수정|편집|다시|재작성|change|edit|revise|reopen).*(설문|서베이|survey|questionnaire|form)",
    re.I,
)
_RE_SERVICE_CHANGE = re.compile(
    r"(서비스|service).*(변경|수정|바꾸|추가|빼|삭제|change|modify|update|add|remove)",
    re.I,
)
_RE_QUOTE_RESEND = re.compile(r"(견적|quote|quotation).*(다시|재발송|보내|send|resend)", re.I)
_RE_PAYMENT_LINK = re.compile(
    r"(결제|payment).*(링크|link|다시|재발송|resend)|"
    r"(링크|link).*(결제|payment)",
    re.I,
)
_RE_SCHEDULE = re.compile(r"(일정|스케줄|schedule|appointment).*(변경|수정|다시|reschedule|change)", re.I)
_RE_AGENT_CHANGE = re.compile(r"(에이전트|agent).*(변경|바꿔|change|switch)", re.I)
_RE_PRICE = re.compile(r"(가격|금액|price|discount|조정|협의|negotiat)", re.I)
_RE_REFUND = re.compile(r"(환불|refund|되돌려|돌려\s*줘|money\s*back)", re.I)
_RE_LEGAL = re.compile(r"(법적|소송|legal|lawsuit|complaint|신고|고발|소비자\s*보호|consumer\s*protect)", re.I)
_RE_STATUS = re.compile(r"(진행|상태|status|어디|어떻게 되고|how is it going)", re.I)


# (regex, intent, confidence, customer_summary_override, internal_reasoning)
# 순서 중요: 먼저 매칭되는 패턴이 우선.
_HEURISTIC_PATTERNS: Tuple[Tuple[Any, Intent, float, str, str], ...] = (
    (_RE_SURVEY_RESUME, Intent.SURVEY_RESUME_REQUEST, 0.75,
     "", "matched survey resume keywords"),
    (_RE_SURVEY_REOPEN, Intent.SURVEY_REOPEN_REQUEST, 0.75,
     "", "matched survey reopen keywords"),
    (_RE_SERVICE_CHANGE, Intent.SURVEY_REOPEN_REQUEST, 0.70,
     "서비스 변경을 위해 설문을 다시 수정할 수 있도록 열어드릴까요?",
     "matched service change keywords → survey reopen"),
    (_RE_QUOTE_RESEND, Intent.QUOTE_RESEND_REQUEST, 0.70,
     "", "matched quote resend keywords"),
    (_RE_PAYMENT_LINK, Intent.PAYMENT_LINK_RESEND_REQUEST, 0.70,
     "", "matched payment link resend keywords"),
    (_RE_SCHEDULE, Intent.SCHEDULE_CHANGE_REQUEST, 0.70,
     "", "matched schedule/appointment change keywords"),
    (_RE_AGENT_CHANGE, Intent.AGENT_CHANGE_REQUEST, 0.65,
     "", "matched agent change keywords"),
    (_RE_PRICE, Intent.PRICING_NEGOTIATION_REQUEST, 0.70,
     "", "matched pricing/negotiation keywords"),
    (_RE_REFUND, Intent.REFUND_REQUEST, 0.70,
     "", "matched refund keywords"),
    (_RE_LEGAL, Intent.LEGAL_COMPLAINT, 0.75,
     "", "matched legal complaint keywords"),
    (_RE_STATUS, Intent.STATUS_CHECK, 0.60,
     "", "matched status check keywords"),
)


def _heuristic_policy(text: str) -> PolicyResult:
    s = (text or "").strip()
    if not s:
        return PolicyResult(
            detected_intent=Intent.GENERAL_QUESTION,
            recommended_action=RecommendedAction.REPLY_WITH_INFORMATION,
            execution_mode=ExecutionMode.REPLY_ONLY,
            confidence=0.2,
            human_review_target=HumanReviewTarget.none,
            customer_facing_summary="무엇을 도와드릴까요? 요청 내용을 조금만 더 자세히 알려주세요.",
            internal_reasoning_summary="empty message",
            should_create_action_offer=False,
            source="heuristic",
        )

    for pattern, intent, conf, summary_override, reasoning in _HEURISTIC_PATTERNS:
        if pattern.search(s):
            entry = get_policy_for_intent(intent)
            return PolicyResult(
                detected_intent=intent,
                recommended_action=entry.recommended_action,
                execution_mode=entry.execution_mode,
                confidence=conf,
                human_review_target=entry.human_review_target,
                customer_facing_summary=summary_override or entry.customer_facing_summary,
                internal_reasoning_summary=reasoning,
                should_create_action_offer=entry.risk_level == RiskLevel.LOW,
                source="heuristic",
            )

    return PolicyResult(
        detected_intent=Intent.GENERAL_QUESTION,
        recommended_action=RecommendedAction.REPLY_WITH_INFORMATION,
        execution_mode=ExecutionMode.REPLY_ONLY,
        confidence=0.45,
        human_review_target=HumanReviewTarget.none,
        customer_facing_summary="문의 내용을 확인했습니다. 필요한 정보를 안내드릴게요.",
        internal_reasoning_summary="no heuristic match; default general question",
        should_create_action_offer=False,
        source="heuristic",
    )


# ---------------------------------------------------------------------------
# Confidence 게이트 (분류 파이프라인)
# ---------------------------------------------------------------------------


def should_call_ollama(heuristic: PolicyResult) -> bool:
    """
    휴리스틱 결과가 충분히 확실한가?
    - confidence >= HEURISTIC_ACCEPT_THRESHOLD 이고 명확한 intent 매치면 LLM 불필요.
    - 그 외(매칭 실패, 낮은 confidence, 일반 문의 기본값)면 Ollama 호출.
    """
    if heuristic.confidence >= HEURISTIC_ACCEPT_THRESHOLD:
        if heuristic.detected_intent != Intent.GENERAL_QUESTION:
            return False
        if "no heuristic match" not in heuristic.internal_reasoning_summary:
            return False
    return True


def should_call_gemini(
    heuristic: PolicyResult,
    ollama_result: Optional[PolicyResult],
) -> bool:
    """
    Ollama 결과로 충분한가? Gemini escalation이 필요한 경우:
    1. Ollama 호출 실패 (None)
    2. Ollama confidence < OLLAMA_ACCEPT_THRESHOLD
    3. Ollama가 high-risk intent를 반환 (Gemini로 재확인)
    4. Ollama가 GENERAL_QUESTION/UNSUPPORTED 반환 (불확실)
    """
    if ollama_result is None:
        return True
    if ollama_result.confidence < OLLAMA_ACCEPT_THRESHOLD:
        return True
    if is_high_risk_intent(ollama_result.detected_intent):
        return True
    if ollama_result.detected_intent in (Intent.GENERAL_QUESTION, Intent.UNSUPPORTED_REQUEST):
        if ollama_result.confidence < 0.8:
            return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_customer_request(
    text: str,
    *,
    context: Optional[Dict[str, Any]] = None,
    allow_llm: bool = True,
) -> PolicyResult:
    """
    비용 절감 분류 파이프라인:  Heuristic → Ollama(로컬) → Gemini(escalation) → safe fallback.

    1. heuristic 먼저. confidence 충분하면 즉시 반환 (LLM 호출 0회).
    2. heuristic 불확실 → Ollama 호출 (로컬, 비용 0).
    3. Ollama 불확실/high-risk → Gemini 호출 (토큰 비용 발생).
    4. 모두 실패 → heuristic 결과를 safe fallback으로 반환.
    """
    heuristic = _heuristic_policy(text)

    if not allow_llm:
        return heuristic

    if not should_call_ollama(heuristic):
        return heuristic

    try:
        from customer_request_llm import call_ollama_classify
        ollama_result = call_ollama_classify(text, context)
    except Exception:
        ollama_result = None

    if ollama_result and not should_call_gemini(heuristic, ollama_result):
        return ollama_result

    try:
        from customer_request_llm import call_gemini_classify
        gemini_result = call_gemini_classify(text, context)
    except Exception:
        gemini_result = None

    if gemini_result is not None:
        return gemini_result

    if ollama_result is not None:
        return ollama_result

    return heuristic


def evaluate_customer_request_policy(
    text: str,
    *,
    context: Optional[Dict[str, Any]] = None,
    llm_adapter: Optional[LLMAdapter] = None,
    allow_llm: bool = True,
) -> PolicyResult:
    """
    레거시 호환 entrypoint. 새 코드는 classify_customer_request() 사용 권장.
    llm_adapter가 지정된 경우에만 기존 경로 사용.
    """
    if llm_adapter:
        try:
            from customer_request_llm import analyze_customer_message_llm
            result = analyze_customer_message_llm(text, context=context, llm_adapter=llm_adapter)
            if result is not None:
                return result
        except Exception:
            pass
        return _heuristic_policy(text)

    return classify_customer_request(text, context=context, allow_llm=allow_llm)
