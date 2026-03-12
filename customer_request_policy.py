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
import logging
import math
import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


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
# Top-K 추천 후보 (학습·ranking용)
# ---------------------------------------------------------------------------

# 한 후보: page_key, score, source (heuristic | llm | merged), reason
RouteCandidateDict = Dict[str, Any]


@dataclass
class ClassificationResult:
    """
    분류 파이프라인 최종 결과. policy는 기존 UI/플로우용, 나머지는 top-k·학습용.
    - heuristic_result / llm_result: raw signal (각각 휴리스틱/LLM 후보 목록).
    - merged_candidates: top-k(기본 3) 병합 후보. 각 항목 {page_key, score, source, reason}.
    - selected_primary_page: UI에 쓰는 1순위 페이지(기존 동작 유지).
    - recommendation_confidence: high | medium | low.
    """
    policy: PolicyResult
    user_message: str = ""
    heuristic_result: Optional[Dict[str, Any]] = None  # {"candidates": [...], "confidence": float}
    llm_result: Optional[Dict[str, Any]] = None       # {"candidates": [...], "confidence": float, "source": "ollama"|"gemini"}
    merged_candidates: List[RouteCandidateDict] = field(default_factory=list)  # top 3
    selected_primary_page: str = ""
    recommendation_confidence: str = ""  # high | medium | low
    normalized_text: str = ""


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
        customer_facing_summary="문의 내용을 확인했습니다. Admin이 빠른 시간 내에 연락드릴게요.",
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
# Hybrid 분류기 (1: semantic → 3: safety gate → 2: local classifier)
# ---------------------------------------------------------------------------

_SEMANTIC_INTENT_EXAMPLES: Dict[Intent, Tuple[str, ...]] = {
    Intent.SURVEY_REOPEN_REQUEST: (
        "설문 내용을 다시 수정하고 싶어요",
        "입력한 정보를 변경하고 싶어요",
        "비행기 도착 시간이 변경됐어요",
        "비행 스케줄이 바뀌었어요",
        "비행 스캐쥴이 바뀌었어요",
        "비행 스캐줄이 바꼈어요",
        "항공편 시간이 바뀌었어요",
        "도착 시간이 잘못됐어요",
        "공항 도착시간을 수정할게요",
    ),
    Intent.SURVEY_RESUME_REQUEST: (
        "설문 이어서 작성하고 싶어요",
        "설문 링크 다시 보내주세요",
        "설문 계속할 수 있나요",
    ),
    Intent.SCHEDULE_CHANGE_REQUEST: (
        "미팅 일정 변경하고 싶어요",
        "예약 시간을 바꾸고 싶어요",
        "약속 스케줄 조정 부탁해요",
    ),
    Intent.QUOTE_RESEND_REQUEST: (
        "견적서 다시 보내주세요",
        "quote resend 부탁해요",
    ),
    Intent.PAYMENT_LINK_RESEND_REQUEST: (
        "결제 링크 다시 보내주세요",
        "payment link 재발송 부탁해요",
    ),
    Intent.STATUS_CHECK: (
        "진행 상태가 어떻게 되나요",
        "지금 어디까지 진행됐나요",
    ),
    Intent.GENERAL_QUESTION: (
        "안녕하세요 문의드립니다",
        "정보를 알려주세요",
        "도와주세요",
    ),
}

_LOCAL_CLASSIFIER_SEED_EXAMPLES: Dict[Intent, Tuple[str, ...]] = {
    Intent.SURVEY_REOPEN_REQUEST: (
        "입국 인원이 바뀌었어요",
        "비자 타입을 잘못 입력했어요",
        "도착 시간이 변경됐어요",
        "비행 스캐쥴이 바뀌었어요",
        "비행 스캐줄이 바꼈어요",
        "비행 스케줄 변경으로 설문 수정 원해요",
        "공항 도착시간 수정할게요",
        "항공편 시간 변경됐어요",
    ),
    Intent.SURVEY_RESUME_REQUEST: (
        "설문 이어서 진행할게요",
        "설문 링크 다시 받을 수 있을까요",
    ),
    Intent.SCHEDULE_CHANGE_REQUEST: (
        "미팅 일정 변경 요청",
        "예약 스케줄 조정 부탁",
        "약속 시간 다시 잡고 싶어요",
    ),
    Intent.QUOTE_RESEND_REQUEST: (
        "견적서 재발송 부탁드려요",
        "quote 다시 보내주세요",
    ),
    Intent.PAYMENT_LINK_RESEND_REQUEST: (
        "결제 링크 재전송 부탁",
        "payment link resend",
    ),
    Intent.STATUS_CHECK: (
        "진행 상태 확인 부탁",
        "지금 진행 상황 알려주세요",
    ),
    Intent.GENERAL_QUESTION: (
        "문의드립니다",
        "도움이 필요해요",
        "확인 부탁드립니다",
    ),
}

_LOCAL_CLASSIFIER_CACHE_TTL_SEC = 300
_LOCAL_CLASSIFIER_CACHE: Dict[str, Any] = {
    "built_at": 0.0,
    "model": None,
}


def _char_ngram_vector(text: str, n: int = 3) -> Counter:
    compact = (text or "").replace(" ", "")
    if not compact:
        return Counter()
    if len(compact) < n:
        return Counter({compact: 1})
    return Counter(compact[i:i + n] for i in range(len(compact) - n + 1))


def _cosine_from_counters(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = 0.0
    for key, val in a.items():
        dot += float(val) * float(b.get(key, 0))
    if dot <= 0:
        return 0.0
    norm_a = math.sqrt(sum(float(v) * float(v) for v in a.values()))
    norm_b = math.sqrt(sum(float(v) * float(v) for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _build_policy_result_from_intent(
    intent: Intent,
    confidence: float,
    source: str,
    reasoning: str,
) -> PolicyResult:
    entry = get_policy_for_intent(intent)
    return PolicyResult(
        detected_intent=intent,
        recommended_action=entry.recommended_action,
        execution_mode=entry.execution_mode,
        confidence=max(0.0, min(float(confidence), 1.0)),
        human_review_target=entry.human_review_target,
        customer_facing_summary=entry.customer_facing_summary,
        internal_reasoning_summary=reasoning,
        should_create_action_offer=entry.risk_level == RiskLevel.LOW,
        source=source,
    )


def _semantic_policy(text: str, context: Optional[Dict[str, Any]] = None) -> Optional[PolicyResult]:
    normalized = normalize_customer_request_text(text)
    if not normalized:
        return None

    input_vec = _char_ngram_vector(normalized, n=3)
    if not input_vec:
        return None

    best_intent: Optional[Intent] = None
    best_score = 0.0
    second_score = 0.0

    for intent, examples in _SEMANTIC_INTENT_EXAMPLES.items():
        intent_score = 0.0
        for sample in examples:
            sample_vec = _char_ngram_vector(normalize_customer_request_text(sample), n=3)
            intent_score = max(intent_score, _cosine_from_counters(input_vec, sample_vec))
        if intent_score > best_score:
            second_score = best_score
            best_score = intent_score
            best_intent = intent
        elif intent_score > second_score:
            second_score = intent_score

    if best_intent is None or best_score < 0.46:
        return None

    margin = max(0.0, best_score - second_score)
    confidence = min(0.9, max(0.35, 0.55 * best_score + 0.45 * margin + 0.25))
    if context and context.get("has_survey_submission") and best_intent == Intent.SURVEY_REOPEN_REQUEST:
        confidence = min(0.92, confidence + 0.04)

    return _build_policy_result_from_intent(
        best_intent,
        confidence,
        source="semantic",
        reasoning=(
            f"semantic similarity best_intent={best_intent.value} "
            f"score={best_score:.3f} margin={margin:.3f}"
        ),
    )


def _token_features(text: str) -> List[str]:
    normalized = normalize_customer_request_text(text)
    if not normalized:
        return []
    tokens = normalized.split()
    tri = list(_char_ngram_vector(normalized, n=3).keys())
    return [f"tok:{t}" for t in tokens] + [f"tri:{g}" for g in tri]


def _load_historical_intent_examples(limit: int = 200) -> List[Tuple[Intent, str]]:
    try:
        from messaging.models import CustomerRequestIntentAnalysis

        rows = (
            CustomerRequestIntentAnalysis.objects
            .exclude(predicted_intent="")
            .exclude(original_text="")
            .order_by("-created_at")[:limit]
        )
        out: List[Tuple[Intent, str]] = []
        for row in rows:
            try:
                intent = Intent(str(row.predicted_intent))
            except Exception:
                continue
            text = (row.original_text or "").strip()
            if not text:
                continue
            out.append((intent, text[:200]))
        return out
    except Exception:
        return []


def _build_local_classifier_model() -> Dict[str, Any]:
    examples: List[Tuple[Intent, str]] = []
    for intent, rows in _LOCAL_CLASSIFIER_SEED_EXAMPLES.items():
        for row in rows:
            examples.append((intent, row))
    examples.extend(_load_historical_intent_examples(limit=200))

    labels = [intent for intent, _ in examples]
    label_counts = Counter(labels)
    if not label_counts:
        return {"vocab": set(), "label_counts": Counter(), "feature_counts": {}, "totals": {}}

    feature_counts: Dict[Intent, Counter] = {intent: Counter() for intent in label_counts}
    totals: Dict[Intent, int] = {intent: 0 for intent in label_counts}
    vocab = set()

    for intent, text in examples:
        feats = _token_features(text)
        for feat in feats:
            feature_counts[intent][feat] += 1
            totals[intent] += 1
            vocab.add(feat)

    return {
        "vocab": vocab,
        "label_counts": label_counts,
        "feature_counts": feature_counts,
        "totals": totals,
    }


def _get_local_classifier_model() -> Dict[str, Any]:
    now = time.time()
    built_at = float(_LOCAL_CLASSIFIER_CACHE.get("built_at") or 0.0)
    model = _LOCAL_CLASSIFIER_CACHE.get("model")
    if model is not None and (now - built_at) < _LOCAL_CLASSIFIER_CACHE_TTL_SEC:
        return model
    model = _build_local_classifier_model()
    _LOCAL_CLASSIFIER_CACHE["model"] = model
    _LOCAL_CLASSIFIER_CACHE["built_at"] = now
    return model


def _local_classifier_policy(text: str, context: Optional[Dict[str, Any]] = None) -> Optional[PolicyResult]:
    feats = _token_features(text)
    if not feats:
        return None

    model = _get_local_classifier_model()
    label_counts: Counter = model.get("label_counts") or Counter()
    if not label_counts:
        return None

    feature_counts: Dict[Intent, Counter] = model.get("feature_counts") or {}
    totals: Dict[Intent, int] = model.get("totals") or {}
    vocab_size = max(1, len(model.get("vocab") or set()))
    total_docs = max(1, sum(label_counts.values()))

    scores: Dict[Intent, float] = {}
    for intent, doc_count in label_counts.items():
        prior = math.log((doc_count + 1) / (total_docs + len(label_counts)))
        feat_counter = feature_counts.get(intent) or Counter()
        denom = (totals.get(intent, 0) + vocab_size)
        score = prior
        for feat in feats:
            score += math.log((feat_counter.get(feat, 0) + 1) / denom)
        scores[intent] = score

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if not ranked:
        return None

    top_intent, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else (top_score - 5.0)
    margin = top_score - second_score
    confidence = 1.0 / (1.0 + math.exp(-margin))
    if context and context.get("has_survey_submission") and top_intent == Intent.SURVEY_REOPEN_REQUEST:
        confidence = min(0.95, confidence + 0.03)

    return _build_policy_result_from_intent(
        top_intent,
        confidence,
        source="local_classifier",
        reasoning=(
            f"local nb classifier top_intent={top_intent.value} margin={margin:.3f} "
            f"samples={sum(label_counts.values())}"
        ),
    )


def _apply_safety_gate(
    base_policy: PolicyResult,
    candidate: Optional[PolicyResult],
    context: Optional[Dict[str, Any]] = None,
) -> Optional[PolicyResult]:
    if candidate is None:
        return None
    if candidate.detected_intent == Intent.GENERAL_QUESTION:
        return None
    if candidate.confidence < 0.66:
        return None

    if (
        candidate.detected_intent in (Intent.SURVEY_REOPEN_REQUEST, Intent.SURVEY_RESUME_REQUEST)
        and context
        and not context.get("has_survey_submission")
    ):
        return None

    if (
        base_policy.detected_intent != Intent.GENERAL_QUESTION
        and base_policy.detected_intent != candidate.detected_intent
        and base_policy.confidence >= 0.75
        and is_high_risk_intent(base_policy.detected_intent)
    ):
        return None

    return PolicyResult(
        detected_intent=candidate.detected_intent,
        recommended_action=candidate.recommended_action,
        execution_mode=candidate.execution_mode,
        confidence=candidate.confidence,
        human_review_target=candidate.human_review_target,
        customer_facing_summary=candidate.customer_facing_summary,
        internal_reasoning_summary=(candidate.internal_reasoning_summary + "; passed safety gate"),
        should_create_action_offer=candidate.should_create_action_offer,
        target_section_ids=candidate.target_section_ids,
        source=f"{candidate.source}_safe",
    )


def _build_semantic_local_ensemble(
    semantic_policy: Optional[PolicyResult],
    local_policy: Optional[PolicyResult],
) -> Optional[PolicyResult]:
    if semantic_policy is None or local_policy is None:
        return None
    if semantic_policy.detected_intent != local_policy.detected_intent:
        return None
    avg_conf = (semantic_policy.confidence + local_policy.confidence) / 2.0
    if avg_conf < 0.68:
        return None
    return _build_policy_result_from_intent(
        semantic_policy.detected_intent,
        min(0.95, avg_conf + 0.03),
        source="semantic_local",
        reasoning=(
            "semantic/local agreement intent="
            + semantic_policy.detected_intent.value
            + f" sem={semantic_policy.confidence:.3f} local={local_policy.confidence:.3f}"
        ),
    )


# ---------------------------------------------------------------------------
# Heuristic classifier — 패턴 테이블
# ---------------------------------------------------------------------------

_RE_MULTI_SPACE = re.compile(r"\s+")
_RE_PUNCT_TO_SPACE = re.compile(r"[^0-9A-Za-z가-힣]+")

_TEXT_NORMALIZATION_RULES: Tuple[Tuple[str, str], ...] = (
    ("바꼈", "바뀌"),
    ("바꼇", "바뀌"),
    ("됬", "됐"),
    ("됫", "됐"),
    ("틀렷", "틀렸"),
    ("잘못입력", "잘못 입력"),
    ("오입력", "잘못 입력"),
    ("재수정", "다시 수정"),
    ("재작성", "다시 작성"),
)

_SURVEY_FIELD_SIGNAL_GROUPS: Dict[str, Tuple[str, ...]] = {
    "entry": ("입국", "출국", "체류", "기간", "입국일", "출국일"),
    "people": ("인원", "인원수", "가족", "동반", "가구", "명"),
    "visa": ("비자", "체류자격", "비자타입", "비자종류"),
    "housing": ("주거", "거주", "주소", "지역", "도시"),
    "airport": ("공항", "픽업", "항공편", "비행편", "비행기", "도착 시간", "도착시간"),
    "applicant": ("이름", "성명", "신청자", "이메일", "전화", "연락처", "여권"),
    "service": ("서비스", "옵션", "진행방식", "지원"),
}

_CHANGE_SIGNAL_GROUPS: Dict[str, Tuple[str, ...]] = {
    "change": ("변경", "수정", "정정", "편집", "바뀌", "바꾸", "고쳐"),
    "mistake": ("잘못", "틀렸", "맞지", "오타", "실수", "오입력"),
    "redo": ("다시", "재입력", "재작성", "다시 작성", "다시 선택"),
    "count_delta": ("늘어", "줄어", "추가", "삭제", "빼", "제외"),
}


def normalize_customer_request_text(text: str) -> str:
    s = unicodedata.normalize("NFKC", (text or "").strip().lower())
    if not s:
        return ""
    for old, new in _TEXT_NORMALIZATION_RULES:
        s = s.replace(old, new)
    s = _RE_PUNCT_TO_SPACE.sub(" ", s)
    return _RE_MULTI_SPACE.sub(" ", s).strip()


def _contains_signal(text: str, compact_text: str, keyword: str) -> bool:
    normalized = normalize_customer_request_text(keyword)
    if not normalized:
        return False
    compact_keyword = normalized.replace(" ", "")
    return normalized in text or compact_keyword in compact_text


def _collect_signal_group_matches(text: str, signal_groups: Dict[str, Tuple[str, ...]]) -> List[str]:
    compact_text = text.replace(" ", "")
    matches: List[str] = []
    for group_name, keywords in signal_groups.items():
        if any(_contains_signal(text, compact_text, keyword) for keyword in keywords):
            matches.append(group_name)
    return matches


def _match_survey_field_change(
    normalized_text: str,
    context: Optional[Dict[str, Any]] = None,
) -> Optional[Tuple[List[str], List[str], float]]:
    field_matches = _collect_signal_group_matches(normalized_text, _SURVEY_FIELD_SIGNAL_GROUPS)
    change_matches = _collect_signal_group_matches(normalized_text, _CHANGE_SIGNAL_GROUPS)
    if not field_matches or not change_matches:
        return None

    confidence = 0.72
    if len(field_matches) >= 2:
        confidence += 0.03
    if context and context.get("has_survey_submission"):
        confidence += 0.03
    return field_matches, change_matches, min(confidence, 0.78)

_RE_SURVEY_RESUME = re.compile(r"(링크|link|resume|이어|계속).*(설문|survey|서베이|form)", re.I)
_RE_SURVEY_REOPEN = re.compile(
    r"(설문|서베이|survey|questionnaire|form).*(수정|편집|다시|재작성|change|edit|revise|reopen)|"
    r"(수정|편집|다시|재작성|change|edit|revise|reopen).*(설문|서베이|survey|questionnaire|form)",
    re.I,
)

# 설문 필드명 언급 패턴 (예: "입국 인원이 바뀌어요", "비자 타입을 잘못 입력했어요")
# → 필드명 + 변경/수정 표현 = 설문 재수정 신호
_RE_SURVEY_FIELD_CHANGE = re.compile(
    r"(입국|인원|기간|비자|주거|지역|공항|도시|이름|성명|신청자|이메일|전화|주소|여권|가구|서비스|지원|항공편|비행편|비행기|도착시간|도착 시간|성).*"
    r"(바뀌|바꼈|바꼇|바꿔|바꾸|잘못|틀렸|맞지|늘어|줄어|다시|수정|변경|편집|정정|수정할|고쳐|정정할)|"
    r"(바뀌|바꼈|바꼇|바꿔|바꾸|잘못|틀렸|맞지|늘어|줄어|다시|수정|변경|편집|정정|수정할|고쳐|정정할).*"
    r"(입국|인원|기간|비자|주거|지역|공항|도시|이름|성명|신청자|이메일|전화|주소|여권|가구|서비스|지원|항공편|비행편|비행기|도착시간|도착 시간|성)",
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
    (_RE_SURVEY_FIELD_CHANGE, Intent.SURVEY_REOPEN_REQUEST, 0.70,
     "설문에 입력하신 정보 중 변경이 필요하신 항목이 있으신 것 같은데, 설문을 다시 수정해드릴까요?",
     "matched survey field change keywords (입국, 비자, 주거 등)"),
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


def _heuristic_policy(text: str, context: Optional[Dict[str, Any]] = None) -> PolicyResult:
    s = (text or "").strip()
    normalized_text = normalize_customer_request_text(s)
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

    semantic_match = _match_survey_field_change(normalized_text, context=context)
    if semantic_match:
        field_matches, change_matches, confidence = semantic_match
        entry = get_policy_for_intent(Intent.SURVEY_REOPEN_REQUEST)
        return PolicyResult(
            detected_intent=Intent.SURVEY_REOPEN_REQUEST,
            recommended_action=entry.recommended_action,
            execution_mode=entry.execution_mode,
            confidence=confidence,
            human_review_target=entry.human_review_target,
            customer_facing_summary="설문에 입력하신 정보 중 변경이 필요하신 항목이 있으신 것 같은데, 설문을 다시 수정해드릴까요?",
            internal_reasoning_summary=(
                "matched normalized survey field groups="
                + ",".join(field_matches)
                + " change signals="
                + ",".join(change_matches)
            ),
            should_create_action_offer=entry.risk_level == RiskLevel.LOW,
            source="heuristic",
        )

    for pattern, intent, conf, summary_override, reasoning in _HEURISTIC_PATTERNS:
        if pattern.search(normalized_text):
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
        customer_facing_summary="문의 내용을 확인했습니다. Admin이 빠른 시간 내에 연락드릴게요.",
        internal_reasoning_summary="no heuristic match; default general question",
        should_create_action_offer=False,
        source="heuristic",
    )


# ---------------------------------------------------------------------------
# Top-K 후보 빌드·병합 (학습/ranking용)
# ---------------------------------------------------------------------------

# 설문 수정 요청 시 휴리스틱이 추천하는 논리적 페이지(서비스에서 section id로 해석)
HEURISTIC_DEFAULT_PAGE_KEY_SURVEY_REOPEN = "희망 서비스"


def _build_heuristic_candidates(heuristic: PolicyResult) -> List[RouteCandidateDict]:
    """휴리스틱 결과를 후보 리스트로 변환. SURVEY_REOPEN 시 '희망 서비스' 1건."""
    if heuristic.detected_intent != Intent.SURVEY_REOPEN_REQUEST:
        return []
    return [{
        "page_key": HEURISTIC_DEFAULT_PAGE_KEY_SURVEY_REOPEN,
        "score": float(heuristic.confidence),
        "source": "heuristic",
        "reason": (heuristic.internal_reasoning_summary or "")[:200],
    }]


def _build_llm_candidates(policy: PolicyResult, source: str) -> List[RouteCandidateDict]:
    """LLM PolicyResult의 target_section_ids를 후보 리스트로 변환."""
    section_ids = getattr(policy, "target_section_ids", ()) or ()
    if not section_ids:
        return []
    reason = (getattr(policy, "internal_reasoning_summary", None) or "")[:200]
    return [
        {
            "page_key": str(sid),
            "score": float(getattr(policy, "confidence", 0)),
            "source": source,
            "reason": reason,
        }
        for sid in section_ids
    ]


# 피드백 점수가 base score 에 미치는 최대 가중치 (boost ∈ [-1,1] → 최대 ±FEEDBACK_WEIGHT)
_FEEDBACK_WEIGHT = 0.25


def _merge_candidates(
    heuristic_candidates: List[RouteCandidateDict],
    llm_candidates: List[RouteCandidateDict],
    top_k: int = 3,
    *,
    feedback_boosts: Optional[Dict[str, float]] = None,
) -> List[RouteCandidateDict]:
    """
    휴리스틱 + LLM 후보를 병합해 상위 top_k개 반환. page_key 기준 중복 시 높은 score 유지.
    feedback_boosts 가 주어지면 집계된 사용자 피드백 점수를 가산해 순위를 보정한다.
    """
    by_key: Dict[str, RouteCandidateDict] = {}
    for c in heuristic_candidates:
        key = (c.get("page_key") or "").strip()
        if key and (key not in by_key or (c.get("score") or 0) > (by_key[key].get("score") or 0)):
            by_key[key] = {**c, "source": c.get("source") or "heuristic"}
    for c in llm_candidates:
        key = (c.get("page_key") or "").strip()
        if key and (key not in by_key or (c.get("score") or 0) > (by_key[key].get("score") or 0)):
            by_key[key] = {**c, "source": c.get("source") or "llm"}
    if feedback_boosts:
        for key, cand in by_key.items():
            boost = feedback_boosts.get(key, 0.0)
            if boost:
                base = float(cand.get("score") or 0)
                adjusted = max(0.0, base + _FEEDBACK_WEIGHT * boost)
                by_key[key] = {**cand, "score": round(adjusted, 4)}
    sorted_list = sorted(by_key.values(), key=lambda x: -(x.get("score") or 0))
    return sorted_list[:top_k]


def _recommendation_confidence_level(confidence: float) -> str:
    """confidence 수치 → high | medium | low."""
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.5:
        return "medium"
    return "low"


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
    feedback_boosts: Optional[Dict[str, float]] = None,
) -> ClassificationResult:
    """
    비용 절감 분류 파이프라인:  Heuristic → Ollama(로컬) → Gemini(escalation) → safe fallback.
    반환: ClassificationResult (policy + top-k 후보·휴리스틱/LLM raw). 기존 UI는 .policy 사용.

    feedback_boosts: {page_key: score_boost} 딕셔너리. None 이면 자동으로 DB/캐시에서 조회한다.
    """
    user_message = (text or "").strip()
    normalized_text = normalize_customer_request_text(text)
    heuristic = _heuristic_policy(text, context=context)
    semantic_policy = _semantic_policy(text, context=context)
    accepted_semantic = _apply_safety_gate(heuristic, semantic_policy, context=context)

    local_policy: Optional[PolicyResult] = None
    accepted_local: Optional[PolicyResult] = None
    if accepted_semantic is None:
        local_policy = _local_classifier_policy(text, context=context)
        accepted_local = _apply_safety_gate(heuristic, local_policy, context=context)

    semantic_local_ensemble = _build_semantic_local_ensemble(semantic_policy, local_policy)
    accepted_ensemble = _apply_safety_gate(heuristic, semantic_local_ensemble, context=context)

    pre_llm_policy = accepted_semantic or accepted_local or accepted_ensemble or heuristic

    heuristic_candidates = _build_heuristic_candidates(heuristic)
    heuristic_result = {
        "candidates": heuristic_candidates,
        "confidence": heuristic.confidence,
        "semantic": semantic_policy.as_dict() if semantic_policy else None,
        "local_classifier": local_policy.as_dict() if local_policy else None,
        "selected_pre_llm_source": pre_llm_policy.source,
    }

    # 피드백 점수 로드 (None 이면 자동 조회, {} 이면 보정 비활성화)
    if feedback_boosts is None:
        try:
            from messaging.feedback_scores import get_feedback_score_boosts
            feedback_boosts = get_feedback_score_boosts()
        except Exception:
            feedback_boosts = {}

    def _make_result(
        policy: PolicyResult,
        llm_result: Optional[Dict[str, Any]] = None,
    ) -> ClassificationResult:
        llm_cands = (llm_result or {}).get("candidates") or []
        merged = _merge_candidates(heuristic_candidates, llm_cands, top_k=3, feedback_boosts=feedback_boosts)
        primary = (merged[0].get("page_key") or "") if merged else ""
        return ClassificationResult(
            policy=policy,
            user_message=user_message,
            heuristic_result=heuristic_result,
            llm_result=llm_result,
            merged_candidates=merged,
            selected_primary_page=primary,
            recommendation_confidence=_recommendation_confidence_level(policy.confidence),
            normalized_text=normalized_text,
        )

    if not allow_llm:
        return _make_result(pre_llm_policy)

    if not should_call_ollama(pre_llm_policy):
        return _make_result(pre_llm_policy)

    ollama_result: Optional[PolicyResult] = None
    try:
        from customer_request_llm import call_ollama_classify
        ollama_result = call_ollama_classify(text, context)
    except Exception as e:
        logger.warning(
            "classify_customer_request: LLM (Ollama) failed, falling back to heuristic: %s",
            e,
            exc_info=True,
        )
        ollama_result = None

    if ollama_result and not should_call_gemini(heuristic, ollama_result):
        llm_result = {
            "candidates": _build_llm_candidates(ollama_result, "ollama"),
            "confidence": ollama_result.confidence,
            "source": "ollama",
        }
        return _make_result(ollama_result, llm_result=llm_result)

    gemini_result: Optional[PolicyResult] = None
    try:
        from customer_request_llm import call_gemini_classify
        gemini_result = call_gemini_classify(text, context)
    except Exception as e:
        logger.warning(
            "classify_customer_request: LLM (Gemini) failed, falling back to heuristic/ollama: %s",
            e,
            exc_info=True,
        )
        gemini_result = None

    if gemini_result is not None:
        llm_result = {
            "candidates": _build_llm_candidates(gemini_result, "gemini"),
            "confidence": gemini_result.confidence,
            "source": "gemini",
        }
        return _make_result(gemini_result, llm_result=llm_result)

    if ollama_result is not None:
        llm_result = {
            "candidates": _build_llm_candidates(ollama_result, "ollama"),
            "confidence": ollama_result.confidence,
            "source": "ollama",
        }
        return _make_result(ollama_result, llm_result=llm_result)

    return _make_result(pre_llm_policy)


def evaluate_customer_request_policy(
    text: str,
    *,
    context: Optional[Dict[str, Any]] = None,
    llm_adapter: Optional[LLMAdapter] = None,
    allow_llm: bool = True,
) -> PolicyResult:
    """
    레거시 호환 entrypoint. 새 코드는 classify_customer_request() 사용 권장.
    llm_adapter가 지정된 경우에만 기존 경로 사용. ClassificationResult 반환 시 .policy만 반환.
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

    classification = classify_customer_request(text, context=context, allow_llm=allow_llm)
    return classification.policy
