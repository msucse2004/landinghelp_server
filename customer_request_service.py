"""
통합 도메인 서비스: 메시지 기반 요청과 견적 수정 요청을 동일한 정책·실행 흐름으로 처리.

- 진입점(messaging inbox / customer quote revision)에 관계없이 동일한 서비스 계층을 거침.
- 뷰는 입력 파싱·응답 포맷만 담당. 비즈니스 로직·상태 전이는 본 모듈에만 존재.
- 고객이 버튼을 누르기 전까지 실제 상태 전이 금지.
- 모든 분류 결과는 CustomerRequestIntentAnalysis 로 영구 저장.
- low-risk 요청은 즉시 실행하지 않고 CustomerActionProposal(제안 객체)을 생성.
  고객이 버튼을 눌러 confirm 한 뒤에만 실행.
- high-risk 요청은 HumanReviewRequest 경로를 유지.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Optional, Tuple

from django.utils import timezone

logger = logging.getLogger(__name__)

# 정책 테이블 기반 조회: customer_request_policy.ACTION_CODE_POLICY / INTENT_POLICY 사용
# (이전의 ACTION_KEY_MAP, _ACTION_TO_PROPOSAL_TYPE 는 정책 테이블로 통합됨)


@dataclass
class RequestContext:
    """요청 진입 후 공통 컨텍스트. intake_customer_request() 반환값."""
    channel: str
    user: Any
    text: str
    conversation: Any
    message: Any
    submission: Optional[Any] = None
    quote: Optional[Any] = None
    change_request: Optional[Any] = None
    policy_result: Optional[Any] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RequestFlowResult:
    """handle_customer_request_flow() 반환값. 호출자가 분류·제안·라우팅 결과를 확인."""
    ctx: Optional[RequestContext] = None
    policy: Optional[Any] = None
    analysis: Optional[Any] = None            # CustomerRequestIntentAnalysis
    proposal: Optional[Any] = None            # CustomerActionProposal or None
    request_id: Optional[str] = None
    should_require_user_confirmation: bool = False
    should_route_to_human_review: bool = False
    error: Optional[str] = None


def intake_customer_request(
    channel: str,
    user: Any,
    text: str,
    *,
    conversation: Optional[Any] = None,
    message: Optional[Any] = None,
    quote: Optional[Any] = None,
) -> Optional[RequestContext]:
    """
    고객 요청 접수. 채널에 따라 대화·메시지·견적·QuoteChangeRequest 생성/연결.
    - messaging_inbox: conversation + message 이미 저장됨. submission = conv.survey_submission.
    - customer_quote_revision: quote 주어지면 공유 대화 생성, 메시지 저장, QuoteChangeRequest 생성 및 LLM 분석.
    반환: RequestContext. 실패 시 None.
    """
    text = (text or "").strip()
    if not text and not message:
        return None

    if channel == "customer_quote_revision" and quote:
        return _intake_quote_revision(user, text, quote)
    if channel == "messaging_inbox" and conversation and message:
        return _intake_messaging(conversation, message, user)
    logger.warning("intake_customer_request: unsupported channel or missing args channel=%s", channel)
    return None


def _intake_quote_revision(user: Any, text: str, quote: Any) -> Optional[RequestContext]:
    """견적 수정 요청 진입: 공유 대화·메시지·QuoteChangeRequest 생성, LLM 분석."""
    from settlement.models import SettlementQuote
    from settlement.notifications import _get_or_create_shared_conversation
    from settlement.services_quote_change import submit_text_change_request
    from messaging.models import Message
    from translations.utils import get_display_text

    submission = getattr(quote, "submission", None)
    if not submission:
        return None

    quote.status = SettlementQuote.Status.NEGOTIATING
    quote.save(update_fields=["status"])

    prefix = get_display_text("견적서 수정 요청", "ko") or "견적서 수정 요청"
    body = prefix + "\n\n" + text
    conv = _get_or_create_shared_conversation(submission, subject_fallback=prefix)
    msg = Message(conversation=conv, sender=user, body=body)
    msg.save()

    change_request, analysis, err = submit_text_change_request(quote, user, text)
    if err:
        logger.warning("intake_quote_revision submit_text_change_request err: %s", err)
        return None

    ctx = RequestContext(
        channel="customer_quote_revision",
        user=user,
        text=text,
        conversation=conv,
        message=msg,
        submission=submission,
        quote=quote,
        change_request=change_request,
        extra={"analysis": analysis},
    )
    return ctx


def _intake_messaging(conversation: Any, message: Any, user: Any) -> RequestContext:
    """메시지 함 진입: 이미 저장된 conv + message, submission만 연결."""
    submission = getattr(conversation, "survey_submission", None)
    return RequestContext(
        channel="messaging_inbox",
        user=user,
        text=(getattr(message, "body", None) or "").strip(),
        conversation=conversation,
        message=message,
        submission=submission,
        quote=None,
        change_request=None,
    )


def analyze_customer_request(ctx: RequestContext) -> Any:
    """
    요청 분류. ClassificationResult 반환.
    - quote 경로이고 이미 LLM 분석(QuoteChangeAnalysis)이 있으면 그 결과를 PolicyResult로 변환해 사용.
    - 그 외에는 classify_customer_request() (Heuristic → Ollama → Gemini) 호출.
    """
    from customer_request_policy import (
        ClassificationResult,
        Intent,
        RecommendedAction,
        ExecutionMode,
        HumanReviewTarget,
        PolicyResult,
        classify_customer_request,
        normalize_customer_request_text,
    )

    analysis = ctx.extra.get("analysis") if ctx.extra else None

    context = {
        "channel": ctx.channel,
        "conversation_type": getattr(ctx.conversation, "type", None),
        "has_survey_submission": bool(ctx.submission),
        "has_appointment": bool(getattr(ctx.conversation, "appointment_id", None)),
    }
    if ctx.submission:
        context["submission_id"] = getattr(ctx.submission, "id", None)
        context["submission_status"] = getattr(ctx.submission, "status", None)
    if ctx.quote:
        context["quote_id"] = ctx.quote.id
        context["quote_status"] = getattr(ctx.quote, "status", None)

    allow_llm = ctx.channel == "messaging_inbox"
    classification = classify_customer_request(
        ctx.text,
        context=context,
        allow_llm=allow_llm,
    )
    policy = classification.policy

    if ctx.channel == "customer_quote_revision":
        selected_primary_page = (getattr(classification, "selected_primary_page", "") or "").strip()
        if not getattr(policy, "target_section_ids", None) and selected_primary_page:
            inferred_section_ids = _infer_target_section_ids_from_primary_page(selected_primary_page)
            if inferred_section_ids:
                policy = replace(policy, target_section_ids=inferred_section_ids)
                classification.policy = policy

        if analysis and (not (policy.customer_facing_summary or "").strip()):
            quote_policy = _policy_from_quote_analysis(analysis, ctx)
            if quote_policy and (quote_policy.customer_facing_summary or "").strip():
                policy = replace(policy, customer_facing_summary=quote_policy.customer_facing_summary)
                classification.policy = policy

    ctx.policy_result = policy
    return classification


def _infer_target_section_ids_from_primary_page(selected_primary_page: str) -> Tuple[int, ...]:
    """추천 1순위 page_key(또는 섹션명)를 SurveySection ID로 변환."""
    page = (selected_primary_page or "").strip()
    if not page:
        return ()

    page_to_section_title = {
        "applicant_info": "신청자 정보",
        "household_info": "입국 인원",
        "region_status": "지역·현황",
        "entry_purpose_stay": "입국 목적·체류",
        "service_selection": "희망 서비스",
        "delivery_preferences": "서비스 진행 방식",
        "other_requests": "기타 의뢰 내용",
        "희망 서비스": "희망 서비스",
        "서비스 진행 방식": "서비스 진행 방식",
        "신청자 정보": "신청자 정보",
        "입국 인원": "입국 인원",
        "지역·현황": "지역·현황",
        "입국 목적·체류": "입국 목적·체류",
        "기타 의뢰 내용": "기타 의뢰 내용",
    }

    title = page_to_section_title.get(page)
    if not title:
        return ()

    try:
        from survey.models import SurveySection

        section = (
            SurveySection.objects.filter(title=title, is_active=True, is_internal=False)
            .order_by('display_order', 'id')
            .first()
        )
        if section:
            return (int(section.id),)
    except Exception:
        logger.warning(
            "_infer_target_section_ids_from_primary_page failed: page=%s",
            page,
            exc_info=True,
        )
    return ()


def _policy_from_quote_analysis(analysis: Any, ctx: RequestContext) -> Optional[Any]:
    """QuoteChangeAnalysis 또는 raw_llm_output 스키마를 PolicyResult로 변환."""
    from customer_request_policy import Intent, RecommendedAction, ExecutionMode, HumanReviewTarget, PolicyResult

    raw = getattr(analysis, "raw_llm_output", None) or {}
    intent_s = raw.get("intent") or getattr(analysis, "detected_intent", None)
    action_s = raw.get("recommended_action")
    mode_s = raw.get("execution_mode")
    target_s = raw.get("human_review_target", "admin")
    conf = float(getattr(analysis, "confidence", 0) or 0)
    customer_summary = (getattr(analysis, "normalized_summary", None) or "").strip() or "요청을 확인했습니다. 검토 후 안내드리겠습니다."
    internal_summary = (raw.get("internal_summary") or "").strip() or (getattr(analysis, "recommended_next_step", None) or "").strip()

    if not intent_s:
        return None
    try:
        intent = Intent(str(intent_s))
    except ValueError:
        intent = Intent.UNSUPPORTED_REQUEST
    if not action_s:
        action_s = "ROUTE_TO_ADMIN_REVIEW" if getattr(analysis, "requires_admin_confirmation", True) else "REPLY_WITH_INFORMATION"
    try:
        action = RecommendedAction(str(action_s))
    except ValueError:
        action = RecommendedAction.ROUTE_TO_ADMIN_REVIEW
    if not mode_s:
        mode_s = "HUMAN_REVIEW_REQUIRED" if getattr(analysis, "requires_admin_confirmation", True) else "REPLY_ONLY"
    try:
        mode = ExecutionMode(str(mode_s))
    except ValueError:
        mode = ExecutionMode.HUMAN_REVIEW_REQUIRED
    try:
        target = HumanReviewTarget(str(target_s))
    except ValueError:
        target = HumanReviewTarget.admin

    return PolicyResult(
        detected_intent=intent,
        recommended_action=action,
        execution_mode=mode,
        confidence=conf,
        human_review_target=target,
        customer_facing_summary=customer_summary,
        internal_reasoning_summary=internal_summary[:1000] if internal_summary else "quote_llm_analysis",
        should_create_action_offer=(mode == ExecutionMode.AUTO_CONFIRMABLE and conf >= 0.6),
        source="quote_llm",
    )


# ---------------------------------------------------------------------------
# 분류 결과·제안 객체 영구 저장
# ---------------------------------------------------------------------------


def _save_intent_analysis(
    ctx: RequestContext,
    policy: Any,
    *,
    request_id: Optional[str] = None,
    classification: Any = None,
) -> Any:
    """PolicyResult → CustomerRequestIntentAnalysis 저장. classification이 있으면 정규화 텍스트와 top-k 후보도 저장."""
    from messaging.models import CustomerRequestIntentAnalysis
    from customer_request_policy import normalize_customer_request_text

    source = getattr(policy, "source", "") or ""
    if not source and ctx.channel == "customer_quote_revision":
        source = "quote_llm"

    raw_output = None
    if ctx.extra and ctx.extra.get("analysis"):
        raw_llm = getattr(ctx.extra["analysis"], "raw_llm_output", None)
        if raw_llm:
            raw_output = raw_llm
    if raw_output is None and classification is not None:
        raw_output = getattr(classification, "llm_result", None)

    normalized_text = normalize_customer_request_text(ctx.text)
    route_candidates = {}
    if classification is not None:
        normalized_text = (getattr(classification, "normalized_text", "") or normalized_text)[:10000]
        route_candidates = {
            "merged_candidates": getattr(classification, "merged_candidates", []) or [],
            "selected_primary_page": getattr(classification, "selected_primary_page", "") or "",
            "recommendation_confidence": getattr(classification, "recommendation_confidence", "") or "",
        }

    record = CustomerRequestIntentAnalysis(
        customer=ctx.user,
        conversation=ctx.conversation,
        message=ctx.message,
        original_text=(ctx.text or "")[:10000],
        normalized_text=normalized_text,
        predicted_intent=str(getattr(policy, "detected_intent", "")),
        predicted_action=str(getattr(policy, "recommended_action", "")),
        execution_mode=str(getattr(policy, "execution_mode", "")),
        confidence=float(getattr(policy, "confidence", 0) or 0),
        source=source or "heuristic",
        raw_model_output=raw_output,
        target_section_ids=list(getattr(policy, "target_section_ids", ()) or []),
        request_id=request_id or None,
        route_candidates=route_candidates,
    )
    record.save()
    logger.info(
        "_save_intent_analysis: id=%s intent=%s source=%s confidence=%.2f",
        record.id, record.predicted_intent, record.source, record.confidence,
    )
    return record


def _attach_feedback_target_message(analysis_record: Any, response_message: Any) -> None:
    if not analysis_record or not response_message:
        return
    try:
        message_id = getattr(response_message, "id", None)
        if not isinstance(message_id, int):
            return
        route_candidates = dict(getattr(analysis_record, "route_candidates", {}) or {})
        route_candidates["feedback_target_message_id"] = message_id
        route_candidates["feedback_enabled"] = True
        analysis_record.route_candidates = route_candidates
        analysis_record.save(update_fields=["route_candidates"])
    except Exception:
        logger.warning(
            "_attach_feedback_target_message failed: analysis_id=%s message_id=%s",
            getattr(analysis_record, "id", None),
            getattr(response_message, "id", None),
            exc_info=True,
        )


def _build_action_payload(ctx: RequestContext, action_code: str) -> dict:
    """실행에 필요한 최소한의 데이터만 포함하는 action_payload 생성."""
    payload: dict = {}
    if ctx.submission and getattr(ctx.submission, "id", None):
        payload["submission_id"] = ctx.submission.id
    if ctx.quote and getattr(ctx.quote, "id", None):
        payload["quote_id"] = ctx.quote.id
    if ctx.change_request and getattr(ctx.change_request, "id", None):
        payload["change_request_id"] = ctx.change_request.id
    section_ids = getattr(ctx.policy_result, "target_section_ids", None)
    if section_ids:
        payload["target_section_ids"] = list(section_ids)
    return payload


def _create_action_proposal(
    analysis_record: Any,
    ctx: RequestContext,
    policy: Any,
    *,
    expires_at: Optional[Any] = None,
) -> Optional[Any]:
    """
    CustomerActionProposal 생성. 동일 (conversation + action_code)에 PROPOSED가 있으면 기존 반환.
    """
    from messaging.models import CustomerActionProposal
    from customer_request_policy import get_policy_for_intent

    entry = get_policy_for_intent(policy.detected_intent)
    action_key = entry.action_code or "unknown"
    proposal_type = entry.proposal_type or "INFO_REPLY"

    if action_key == "reopen_survey" and not _can_execute_offer(ctx, action_key):
        logger.info("_create_action_proposal: reopen_survey not executable, skip")
        return None

    existing = CustomerActionProposal.objects.filter(
        status=CustomerActionProposal.Status.PROPOSED,
        action_code=action_key,
    )
    if ctx.submission:
        existing = existing.filter(submission_id=ctx.submission.id)
    elif ctx.conversation:
        existing = existing.filter(conversation_id=ctx.conversation.id)
    existing = existing.first()
    if existing:
        return existing

    title = entry.offer_title or "액션 확인"
    body = (getattr(policy, "customer_facing_summary", "") or "").strip()

    proposal = CustomerActionProposal(
        analysis=analysis_record,
        proposal_type=proposal_type,
        title=title,
        body=body or "",
        action_code=action_key,
        action_payload=_build_action_payload(ctx, action_key),
        status=CustomerActionProposal.Status.PROPOSED,
        submission=ctx.submission,
        quote=ctx.quote,
        conversation=ctx.conversation,
        expires_at=expires_at,
    )
    proposal.save()
    _log_feedback(proposal, "PROPOSAL_SHOWN", actor=None)
    logger.info(
        "_create_action_proposal: id=%s type=%s code=%s",
        proposal.id, proposal_type, action_key,
    )
    return proposal


def _log_feedback(
    proposal: Any,
    event_type: str,
    actor: Optional[Any] = None,
    payload: Optional[dict] = None,
) -> Any:
    """CustomerActionFeedbackLog 이벤트 1건 추가 (append-only)."""
    from messaging.models import CustomerActionFeedbackLog
    log = CustomerActionFeedbackLog(
        proposal=proposal,
        event_type=event_type,
        event_payload=payload or {},
        actor=actor,
    )
    log.save()
    return log


def _build_learning_signal(
    proposal: Any,
    user_feedback: str,
    *,
    final_outcome: str = "",
    followup_text: str = "",
    extra: Optional[dict] = None,
) -> dict:
    """
    향후 retrieval/classifier 학습에 사용할 structured payload.
    export 가능한 일관된 형식으로 저장.
    """
    analysis = getattr(proposal, "analysis", None)
    signal: dict = {
        "predicted_intent": str(getattr(analysis, "predicted_intent", "")) if analysis else "",
        "predicted_action": str(getattr(analysis, "predicted_action", "")) if analysis else "",
        "confidence": float(getattr(analysis, "confidence", 0)) if analysis else 0.0,
        "source": str(getattr(analysis, "source", "")) if analysis else "",
        "action_code": getattr(proposal, "action_code", "") or "",
        "user_feedback": user_feedback,
        "final_outcome": final_outcome,
        "original_text": (getattr(analysis, "original_text", "") or "")[:500] if analysis else "",
    }
    if followup_text:
        signal["followup_text"] = followup_text[:500]
    if extra:
        signal.update(extra)
    return signal


# ---------------------------------------------------------------------------
# 제안 확인/거절 (고객 버튼 클릭)
# ---------------------------------------------------------------------------


def confirm_proposal(proposal_id: int, user: Any) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    고객이 제안을 승인. PROPOSED → CONFIRMED → 실행 → EXECUTED/FAILED.
    기존 _execute_* 함수 재사용. idempotent: 이미 EXECUTED면 성공 반환.
    transaction.atomic으로 상태 전이를 보호하고, 예외 발생 시 FAILED로 기록.
    실행 성공/실패 시 고객 대화에 결과 메시지를 전송.

    반환: (success, error_message, customer_message)
    """
    from django.db import transaction
    from messaging.models import CustomerActionProposal

    proposal = (
        CustomerActionProposal.objects
        .filter(id=proposal_id)
        .select_related("submission", "quote", "conversation", "analysis")
        .first()
    )
    if not proposal:
        return False, "제안을 찾을 수 없습니다.", None
    if proposal.status == CustomerActionProposal.Status.EXECUTED:
        return True, None, None
    if proposal.status != CustomerActionProposal.Status.PROPOSED:
        return False, "이미 처리되었거나 만료된 제안입니다.", None

    now = timezone.now()
    if proposal.expires_at and proposal.expires_at < now:
        proposal.status = CustomerActionProposal.Status.EXPIRED
        proposal.save(update_fields=["status", "updated_at"])
        _log_feedback(proposal, "PROPOSAL_EXPIRED", actor=user)
        return False, "제안이 만료되었습니다.", None

    # Phase 1: PROPOSED → CONFIRMED (atomic)
    with transaction.atomic():
        proposal.status = CustomerActionProposal.Status.CONFIRMED
        proposal.confirmed_at = now
        proposal.confirmed_by = user
        proposal.save(update_fields=["status", "confirmed_at", "confirmed_by", "updated_at"])
        _log_feedback(
            proposal, "USER_CONFIRMED", actor=user,
            payload=_build_learning_signal(proposal, "confirmed"),
        )

    try:
        request_id = (getattr(getattr(proposal, "analysis", None), "request_id", None) or "").strip()
        route_candidates = getattr(getattr(proposal, "analysis", None), "route_candidates", None)
        route_candidates = route_candidates if isinstance(route_candidates, dict) else {}
        selected_primary_page = (route_candidates.get("selected_primary_page") or "").strip() or None
        if request_id:
            from messaging.feedback_events import log_suggestion_clicked

            log_suggestion_clicked(
                request_id,
                user_id=getattr(user, "id", None),
                survey_submission_id=getattr(proposal, "submission_id", None),
                page_key=selected_primary_page,
                clicked_item="proposal_confirm",
                metadata={
                    "suggested_page_key": selected_primary_page,
                },
            )
    except Exception:
        logger.warning("confirm_proposal: suggestion_clicked logging failed proposal_id=%s", proposal_id, exc_info=True)

    # Phase 2: 실행 (예외 포함 안전 처리)
    _log_feedback(proposal, "ACTION_STARTED", actor=user)

    try:
        success, err = _run_proposal_action(proposal, user)
    except Exception as exc:
        logger.exception(
            "confirm_proposal: unexpected exception during action proposal_id=%s code=%s",
            proposal_id, proposal.action_code,
        )
        success, err = False, f"예기치 않은 오류: {str(exc)[:500]}"

    # Phase 3: 결과 반영 (atomic)
    customer_msg = None
    with transaction.atomic():
        if success:
            proposal.status = CustomerActionProposal.Status.EXECUTED
            proposal.executed_at = timezone.now()
            proposal.save(update_fields=["status", "executed_at", "updated_at"])
            _log_feedback(
                proposal, "ACTION_SUCCEEDED", actor=user,
                payload=_build_learning_signal(proposal, "confirmed", final_outcome="success"),
            )
            customer_msg = _confirm_success_message(proposal.action_code)
        else:
            proposal.status = CustomerActionProposal.Status.FAILED
            proposal.failure_reason = (err or "")[:2000]
            proposal.save(update_fields=["status", "failure_reason", "updated_at"])
            _log_feedback(
                proposal, "ACTION_FAILED", actor=user,
                payload=_build_learning_signal(
                    proposal, "confirmed", final_outcome="failed",
                    extra={"error": err or ""},
                ),
            )
            customer_msg = _confirm_failure_message(proposal.action_code, err)

    # Phase 4: 고객 대화에 결과 메시지 전송 (실패해도 proposal 상태 유지)
    if customer_msg and proposal.conversation:
        try:
            staff_sender = _pick_staff_sender(proposal.conversation)
            if staff_sender:
                create_customer_auto_reply(proposal.conversation, customer_msg, staff_sender)
        except Exception as e:
            logger.warning("confirm_proposal: auto-reply failed proposal_id=%s: %s", proposal_id, e)

    if success:
        return True, None, customer_msg
    return False, err or "실행에 실패했습니다.", customer_msg


def decline_proposal(proposal_id: int, user: Any) -> Tuple[bool, Optional[str]]:
    """
    고객이 제안을 거절. PROPOSED → DECLINED.
    transaction.atomic으로 상태 전이를 보호.
    """
    from django.db import transaction
    from messaging.models import CustomerActionProposal

    proposal = CustomerActionProposal.objects.filter(id=proposal_id).first()
    if not proposal:
        return False, "제안을 찾을 수 없습니다."
    if proposal.status != CustomerActionProposal.Status.PROPOSED:
        return False, "이미 처리된 제안입니다."

    with transaction.atomic():
        proposal.status = CustomerActionProposal.Status.DECLINED
        proposal.declined_at = timezone.now()
        proposal.save(update_fields=["status", "declined_at", "updated_at"])
        _log_feedback(
            proposal, "USER_DECLINED", actor=user,
            payload=_build_learning_signal(proposal, "declined"),
        )

    if proposal.conversation:
        try:
            staff_sender = _pick_staff_sender(proposal.conversation)
            if staff_sender:
                body = "요청이 취소되었습니다. 다른 도움이 필요하시면 메시지를 보내 주세요."
                create_customer_auto_reply(proposal.conversation, body, staff_sender)
        except Exception as e:
            logger.warning("decline_proposal: auto-reply failed proposal_id=%s: %s", proposal_id, e)

    return True, None


def _get_action_executors() -> Dict[str, Any]:
    """
    action_code → 실행 함수 매핑.
    새 auto-confirmable action 추가 시 여기에 등록.
    """
    return {
        "reopen_survey": _execute_survey_reopen,
        "resume_survey": _execute_survey_resume,
        "resend_quote": _execute_quote_resend,
        "open_revision_flow": _execute_open_revision_flow,
        "resend_payment_link": _execute_payment_link_resend,
    }


def _run_proposal_action(proposal: Any, user: Any) -> Tuple[bool, Optional[str]]:
    """action_code에 따라 기존 실행 함수 디스패치."""
    key = getattr(proposal, "action_code", "") or ""
    executor = _get_action_executors().get(key)
    if executor:
        return executor(proposal, user)
    return False, f"지원하지 않는 액션입니다: {key}"


def _confirm_success_message(action_code: str) -> str:
    """실행 성공 시 고객에게 보낼 응답 메시지. 정책 테이블에서 조회."""
    from customer_request_policy import get_policy_for_action_code
    entry = get_policy_for_action_code((action_code or "").strip())
    return entry.success_message if entry else "요청이 처리되었습니다."


def _confirm_failure_message(action_code: str, error: Optional[str]) -> str:
    """실행 실패 시 고객에게 보낼 응답 메시지."""
    base = "요청 처리 중 문제가 발생했습니다."
    if error and len(error) < 200:
        base += f" ({error})"
    base += " 다시 시도하거나, 관리자에게 문의해 주세요."
    return base


# ---------------------------------------------------------------------------
# Legacy: CustomerActionOffer 호환 (기존 오퍼가 DB에 남아있을 수 있으므로 유지)
# ---------------------------------------------------------------------------


def create_action_offer(
    ctx: RequestContext,
    policy: Any,
    title: str,
    body: str,
    button_label: str,
    button_action_key: str,
    *,
    expires_at: Optional[Any] = None,
) -> Optional[Any]:
    """
    액션 제안(버튼) 생성. 서버 truth 기반.
    동일 (submission 또는 change_request) + button_action_key 에 대해 이미 PENDING 오퍼가 있으면 생성하지 않고 기존 반환(idempotent).
    """
    from settlement.models import CustomerActionOffer

    submission = ctx.submission
    change_request = ctx.change_request
    if not submission and not change_request:
        logger.info("create_action_offer: no submission or change_request, skip")
        return None

    existing = CustomerActionOffer.objects.filter(
        status=CustomerActionOffer.Status.PENDING,
        button_action_key=button_action_key,
    )
    if submission:
        existing = existing.filter(submission_id=submission.id)
    else:
        existing = existing.filter(change_request_id=change_request.id)
    existing = existing.first()
    if existing:
        return existing

    # reopen_survey: 실행 불가 상태(AGENT_ASSIGNMENT 등)에서는 오퍼를 만들지 않음(버튼 노출 방지)
    if button_action_key == "reopen_survey" and not _can_execute_offer(ctx, button_action_key):
        logger.info("create_action_offer: reopen_survey not executable for submission, skip")
        return None

    offer = CustomerActionOffer(
        title=title or "",
        body=body or "",
        button_label=button_label,
        button_action_key=button_action_key,
        submission=submission,
        quote=ctx.quote,
        change_request=change_request,
        conversation=ctx.conversation,
        trigger_message=ctx.message,
        expires_at=expires_at,
        status=CustomerActionOffer.Status.PENDING,
        can_execute=_can_execute_offer(ctx, button_action_key),
    )
    offer.save()
    logger.info("create_action_offer: id=%s key=%s", offer.id, button_action_key)
    return offer


def _can_execute_offer(ctx: RequestContext, action_key: str) -> bool:
    """현재 컨텍스트에서 해당 액션 실행 가능 여부."""
    from survey.models import SurveySubmission

    sub = ctx.submission
    if action_key == "reopen_survey" and sub:
        if getattr(sub, "can_customer_edit", lambda: False)():
            return False
        return getattr(sub, "status", None) in (
            SurveySubmission.Status.SUBMITTED,
            SurveySubmission.Status.AWAITING_PAYMENT,
        )
    if action_key == "resume_survey" and sub:
        # REVISION_REQUESTED 상태에서만 재노출 허용
        return getattr(sub, "status", None) == SurveySubmission.Status.REVISION_REQUESTED
    if action_key == "resend_quote" and (ctx.quote or sub):
        return True
    if action_key == "resend_payment_link" and (ctx.quote or sub):
        return True
    if action_key == "open_revision_flow" and sub:
        return True
    return True


def _create_section_requests_for_submission(
    submission: Any,
    section_ids: tuple,
    *,
    requested_by: Optional[Any] = None,
    message: str = "",
) -> int:
    """LLM이 분석한 target_section_ids로 SurveySubmissionSectionRequest 생성. 이미 있는 건 스킵."""
    if not section_ids:
        return 0
    from survey.models import SurveySection, SurveySubmissionSectionRequest

    valid_ids = set(
        SurveySection.objects.filter(
            id__in=section_ids, is_active=True, is_internal=False,
        ).values_list("id", flat=True)
    )
    existing_ids = set(
        SurveySubmissionSectionRequest.objects.filter(
            submission=submission, resolved_at__isnull=True,
        ).values_list("section_id", flat=True)
    )
    created = 0
    for sid in section_ids:
        if sid in valid_ids and sid not in existing_ids:
            SurveySubmissionSectionRequest.objects.create(
                submission=submission,
                section_id=sid,
                message=message,
                requested_by=requested_by,
            )
            created += 1
    if created:
        logger.info("_create_section_requests: submission=%s sections=%s created=%d", submission.id, section_ids, created)
    return created


def execute_confirmed_action(offer_id: int, user: Any) -> Tuple[bool, Optional[str]]:
    """
    고객이 버튼을 눌렀을 때 실행. idempotent: 이미 실행된 오퍼는 재실행 없이 성공 반환.
    실제 상태 전이는 여기서만 수행.
    """
    from settlement.models import CustomerActionOffer

    offer = CustomerActionOffer.objects.filter(id=offer_id).select_related(
        "submission", "quote", "change_request"
    ).first()
    if not offer:
        return False, "제안을 찾을 수 없습니다."
    if offer.status == CustomerActionOffer.Status.EXECUTED:
        return True, None
    if offer.status != CustomerActionOffer.Status.PENDING:
        return False, "이미 만료되었거나 취소된 제안입니다."
    if not offer.can_execute:
        return False, "현재 이 작업을 실행할 수 없습니다."

    now = timezone.now()
    if offer.expires_at and offer.expires_at < now:
        offer.status = CustomerActionOffer.Status.EXPIRED
        offer.save(update_fields=["status", "updated_at"])
        return False, "제안이 만료되었습니다."

    success, err = _run_action(offer, user)
    if not success:
        return False, err or "실행에 실패했습니다."

    offer.status = CustomerActionOffer.Status.EXECUTED
    offer.executed_at = now
    offer.executed_by = user
    offer.save(update_fields=["status", "executed_at", "executed_by", "updated_at"])
    return True, None


def _run_action(offer: Any, user: Any) -> Tuple[bool, Optional[str]]:
    """button_action_key에 따라 실제 상태 전이 수행. 고객 버튼 클릭 시에만 호출."""
    key = getattr(offer, "button_action_key", "") or ""
    executor = _get_action_executors().get(key)
    if executor:
        return executor(offer, user)
    return False, "지원하지 않는 액션입니다."


def _execute_survey_reopen(offer: Any, user: Any) -> Tuple[bool, Optional[str]]:
    """설문 재개 실행: submission REVISION_REQUESTED, 견적 supersede, 고객 메시지. (버튼 클릭 시에만 호출)"""
    from survey.models import SurveySubmission, SurveySubmissionEvent
    from settlement.models import SettlementQuote
    from django.db.models import F

    sub = getattr(offer, "submission", None)
    if not sub:
        return False, "연결된 설문이 없습니다."
    allowed = (SurveySubmission.Status.SUBMITTED, SurveySubmission.Status.AWAITING_PAYMENT)
    if getattr(sub, "status", None) not in allowed:
        return False, "현재 상태에서는 설문 수정을 열 수 없습니다."

    now = timezone.now()
    sub.status = SurveySubmission.Status.REVISION_REQUESTED
    sub.revision_requested_at = now
    sub.revision_requested_message = "고객이 버튼을 눌러 설문 수정을 요청했습니다."
    sub.save(update_fields=["status", "revision_requested_at", "revision_requested_message", "updated_at"])
    SurveySubmission.objects.filter(pk=sub.pk).update(revision_count=F("revision_count") + 1)
    sub.refresh_from_db(fields=["revision_count"])

    SurveySubmissionEvent.objects.create(
        submission=sub,
        event_type=SurveySubmissionEvent.EventType.REVISION_REQUESTED,
        created_by=user,
        meta={"source": "customer_action_offer", "offer_id": offer.id},
    )

    sent_quote = (
        SettlementQuote.objects.filter(
            submission=sub,
            status=SettlementQuote.Status.FINAL_SENT,
        ).order_by("-sent_at", "-updated_at").first()
    )
    if sent_quote:
        sent_quote.revision_superseded_at = now
        sent_quote.save(update_fields=["revision_superseded_at"])

    try:
        from settlement.notifications import send_survey_reopened_customer_message
        send_survey_reopened_customer_message(sub, language_code="ko", request=None)
    except Exception as e:
        logger.warning("send_survey_reopened_customer_message failed: %s", e)

    return True, None


def _execute_survey_resume(offer: Any, user: Any) -> Tuple[bool, Optional[str]]:
    """
    설문 이어쓰기 실행: 상태 전이 없이 설문 수정/이어쓰기 링크만 다시 안내.
    - REVISION_REQUESTED 상태에서만 허용.
    """
    from survey.models import SurveySubmission
    from settlement.notifications import send_survey_reopened_customer_message

    sub = getattr(offer, "submission", None)
    if not sub:
        return False, "연결된 설문이 없습니다."
    if getattr(sub, "status", None) != SurveySubmission.Status.REVISION_REQUESTED:
        return False, "현재 상태에서는 설문을 이어서 작성할 수 없습니다."

    ok = send_survey_reopened_customer_message(sub, language_code="ko", request=None)
    if not ok:
        return False, "설문 링크를 다시 보내는 데 실패했습니다."
    return True, None


def _execute_quote_resend(offer: Any, user: Any) -> Tuple[bool, Optional[str]]:
    """
    견적서 다시 보내기:
    - superseded 되지 않은 최신 FINAL_SENT 견적만 재발송.
    - hard delete 없이 기존 quote 이력을 유지.
    """
    from settlement.models import SettlementQuote
    from settlement.notifications import send_quote_release_message

    quote = getattr(offer, "quote", None)
    sub = getattr(offer, "submission", None)

    q = None
    if quote and getattr(quote, "status", None) == SettlementQuote.Status.FINAL_SENT and not getattr(
        quote, "revision_superseded_at", None
    ):
        q = quote
    elif sub:
        q = (
            SettlementQuote.objects.filter(
                submission=sub,
                status=SettlementQuote.Status.FINAL_SENT,
                revision_superseded_at__isnull=True,
            )
            .order_by("-sent_at", "-updated_at")
            .first()
        )
    if not q:
        return False, "다시 보낼 수 있는 견적이 없습니다."

    ok = send_quote_release_message(q, language_code="ko")
    if not ok:
        return False, "견적서를 다시 보내는 데 실패했습니다."
    return True, None


def _execute_payment_link_resend(offer: Any, user: Any) -> Tuple[bool, Optional[str]]:
    """
    결제 링크 재발송: FINAL_SENT 상태의 견적에 대해 결제 페이지 링크를 공유 대화에 메시지로 전송.
    """
    from settlement.models import SettlementQuote
    from settlement.quote_email import get_quote_payment_link
    from settlement.notifications import _get_or_create_shared_conversation

    quote = getattr(offer, "quote", None)
    sub = getattr(offer, "submission", None)

    q = None
    if quote and getattr(quote, "status", None) == SettlementQuote.Status.FINAL_SENT and not getattr(
        quote, "revision_superseded_at", None
    ):
        q = quote
    elif sub:
        q = (
            SettlementQuote.objects.filter(
                submission=sub,
                status=SettlementQuote.Status.FINAL_SENT,
                revision_superseded_at__isnull=True,
            )
            .order_by("-sent_at", "-updated_at")
            .first()
        )
    if not q:
        return False, "결제 가능한 견적이 없습니다."

    payment_link = get_quote_payment_link(q)
    if not payment_link:
        return False, "결제 링크를 생성할 수 없습니다."

    conv = getattr(offer, "conversation", None)
    if not conv and sub:
        conv = _get_or_create_shared_conversation_safe(sub)
    if not conv:
        return False, "대화를 찾을 수 없습니다."

    staff_sender = _pick_staff_sender(conv)
    if not staff_sender:
        return False, "메시지를 발송할 수 없습니다."

    body = f"결제 링크를 다시 보내드립니다.\n\n{payment_link}"
    create_customer_auto_reply(conv, body, staff_sender)
    return True, None


def _get_or_create_shared_conversation_safe(submission: Any):
    """settlement.notifications._get_or_create_shared_conversation를 안전하게 호출."""
    try:
        from settlement.notifications import _get_or_create_shared_conversation
        return _get_or_create_shared_conversation(submission, subject_fallback="결제 안내")
    except Exception as e:
        logger.warning("_get_or_create_shared_conversation failed: %s", e)
        return None


def _execute_open_revision_flow(offer: Any, user: Any) -> Tuple[bool, Optional[str]]:
    """
    수정 요청 플로우 열기 (action creation only):
    - 별도의 QuoteChangeRequest 가 없고 제출/견적이 있으면 OPEN 상태 요청을 생성.
    - 설문/견적 status 는 변경하지 않음.
    """
    from settlement.models import QuoteChangeRequest, SettlementQuote

    sub = getattr(offer, "submission", None)
    cr = getattr(offer, "change_request", None)
    if cr:
        return True, None
    if not sub:
        return False, "연결된 설문이 없습니다."
    if not getattr(sub, "user_id", None):
        return False, "요청자를 찾을 수 없습니다."

    quote = getattr(offer, "quote", None)
    if not quote:
        quote = (
            SettlementQuote.objects.filter(
                submission=sub,
                status=SettlementQuote.Status.FINAL_SENT,
                revision_superseded_at__isnull=True,
            )
            .order_by("-sent_at", "-updated_at")
            .first()
        )
    if not quote:
        return False, "수정 가능한 견적이 없습니다."

    existing = QuoteChangeRequest.objects.filter(
        submission=sub,
        quote=quote,
        status__in=(
            QuoteChangeRequest.Status.OPEN,
            QuoteChangeRequest.Status.ANALYZED,
            QuoteChangeRequest.Status.IN_REVIEW,
            QuoteChangeRequest.Status.CUSTOMER_ACTION_REQUIRED,
        ),
    ).first()
    if existing:
        return True, None

    QuoteChangeRequest.objects.create(
        submission=sub,
        quote=quote,
        requested_by=sub.user,
        source_type=QuoteChangeRequest.SourceType.TEXT,
        status=QuoteChangeRequest.Status.OPEN,
        customer_message="고객이 버튼을 눌러 견적 수정 요청을 시작했습니다.",
    )
    return True, None

def _human_review_auto_reply_body(status: str, policy: Any) -> str:
    """
    사람 검토 요청 시 고객에게 보낼 자동 응답 문구. 과도한 약속 금지.
    status: RECEIVED | IN_REVIEW | NEEDS_INFO | COMPLETED
    """
    if status == "RECEIVED":
        return "요청이 접수되었습니다. 검토 후 안내드리겠습니다."
    if status == "IN_REVIEW":
        return "검토 중입니다. 잠시만 기다려 주세요."
    if status == "NEEDS_INFO":
        return "추가 확인이 필요할 수 있습니다. 담당자가 연락드릴 예정입니다."
    if status == "COMPLETED":
        suggested = (getattr(policy, "customer_facing_summary", None) or "").strip()
        if suggested and len(suggested) < 500:
            return suggested
        return "요청에 대한 검토가 완료되었습니다. 궁금한 점이 있으면 메시지로 문의해 주세요."
    return "요청이 접수되었습니다. 검토 후 안내드리겠습니다."


def route_request_for_human_review(ctx: RequestContext, policy: Any) -> Optional[Any]:
    """
    HUMAN_REVIEW_REQUIRED 시 내부 검토 레코드 생성 및 admin/agent/admin_then_agent 로 라우팅.
    - HumanReviewRequest 생성: 원문, intent, recommended_action, execution_mode, confidence,
      suggested_internal_next_step, suggested_customer_reply, 관련 submission/quote/change_request 저장.
    - quote 경로면 QuoteChangeRequest 를 IN_REVIEW 로 전이.
    반환: 생성된 HumanReviewRequest 또는 None.
    """
    from settlement.models import HumanReviewRequest, QuoteChangeRequest

    target = (getattr(policy, "human_review_target", None) or "admin")
    target_value = str(target).strip().lower() if target else "admin"
    if target_value not in ("admin", "agent", "admin_then_agent"):
        target_value = "admin"

    record = HumanReviewRequest(
        conversation=ctx.conversation,
        trigger_message=ctx.message,
        submission=ctx.submission,
        quote=ctx.quote,
        change_request=ctx.change_request,
        requested_by=ctx.user,
        review_target=target_value,
        status=HumanReviewRequest.Status.RECEIVED,
        original_message=ctx.text[:10000] if ctx.text else "",
        detected_intent=str(getattr(policy, "detected_intent", "") or "")[:80],
        recommended_action=str(getattr(policy, "recommended_action", "") or "")[:80],
        execution_mode=str(getattr(policy, "execution_mode", "") or "")[:40],
        confidence=float(getattr(policy, "confidence", 0) or 0),
        suggested_internal_next_step=(getattr(policy, "internal_reasoning_summary", None) or "")[:2000],
        suggested_customer_reply=(getattr(policy, "customer_facing_summary", None) or "")[:2000],
    )
    record.save()

    if ctx.change_request and getattr(ctx.change_request, "status", None) == QuoteChangeRequest.Status.ANALYZED:
        ctx.change_request.status = QuoteChangeRequest.Status.IN_REVIEW
        ctx.change_request.save(update_fields=["status", "updated_at"])

    return record


def complete_human_review(
    review_id: int,
    completed_by: Any,
    *,
    note: str = "",
    customer_message: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    담당자가 검토를 완료할 때 호출. 해당 요청을 COMPLETED 로 종료하고,
    customer_message 가 있으면 고객 대화에 안내 메시지를 남김.
    중복 호출 시 이미 COMPLETED 이면 성공으로 처리(idempotent).
    """
    from settlement.models import HumanReviewRequest

    record = HumanReviewRequest.objects.filter(id=review_id).select_related("conversation").first()
    if not record:
        return False, "검토 요청을 찾을 수 없습니다."
    if record.status == HumanReviewRequest.Status.COMPLETED:
        return True, None

    now = timezone.now()
    record.status = HumanReviewRequest.Status.COMPLETED
    record.completed_at = now
    if note is not None:
        record.completed_note = (record.completed_note or "") + ("\n" + note).strip()
    if getattr(completed_by, "id", None):
        record.assigned_to = completed_by
    record.save(update_fields=["status", "completed_at", "completed_note", "assigned_to", "updated_at"])

    conv = record.conversation
    sender = completed_by or ( _pick_staff_sender(conv) if conv else None )
    if conv and sender:
        body = (customer_message or "").strip() if customer_message else ""
        if not body:
            body = _human_review_auto_reply_body(
                "COMPLETED",
                type("_", (), {"customer_facing_summary": (record.suggested_customer_reply or "").strip()})(),
            )
        create_customer_auto_reply(conv, body, sender)

    return True, None


def admin_initiated_reopen_submission(
    submission_id: int,
    admin_user: Any,
    *,
    change_request: Optional[Any] = None,
    request: Optional[Any] = None,
    target_section_ids: Optional[tuple] = None,
) -> Tuple[bool, Optional[Any], Optional[str]]:
    """
    Admin이 고객 요청 없이 설문 수정 허용.
    - 즉시 submission을 REVISION_REQUESTED로 전환하고, 기존 FINAL_SENT 견적을 supersede 처리.
    - target_section_ids가 있으면 해당 섹션만 수정 가능하도록 SurveySubmissionSectionRequest 생성.
    - 고객은 메시지함/대시보드에서 '설문 수정하기' 링크를 눌러 바로 수정 시작 가능 (추가 확인 불필요).
    - 이미 REVISION_REQUESTED 이면 idempotent 성공.
    반환: (success, offer_or_none, error_message)
    """
    from django.db.models import F
    from survey.models import SurveySubmission, SurveySubmissionEvent
    from settlement.models import SettlementQuote
    from settlement.notifications import _get_or_create_shared_conversation

    submission = SurveySubmission.objects.filter(id=submission_id).select_related("user").first()
    if not submission:
        return False, None, "해당 설문 제출을 찾을 수 없습니다."

    status = getattr(submission, "status", None)
    if status == SurveySubmission.Status.REVISION_REQUESTED:
        return True, None, None

    if status not in (SurveySubmission.Status.SUBMITTED, SurveySubmission.Status.AWAITING_PAYMENT):
        return False, None, "제출(SUBMITTED) 또는 결제대기(AWAITING_PAYMENT) 상태에서만 설문 수정 허용을 보낼 수 있습니다."

    now = timezone.now()

    submission.status = SurveySubmission.Status.REVISION_REQUESTED
    submission.revision_requested_at = now
    submission.revision_requested_message = "관리자가 설문 수정을 허용했습니다."
    submission.save(update_fields=["status", "revision_requested_at", "revision_requested_message", "updated_at"])
    SurveySubmission.objects.filter(pk=submission.pk).update(revision_count=F("revision_count") + 1)

    SurveySubmissionEvent.objects.create(
        submission=submission,
        event_type=SurveySubmissionEvent.EventType.REOPENED,
        created_by=admin_user,
        meta={"admin_initiated": True, "target_section_ids": list(target_section_ids or [])},
    )

    if target_section_ids:
        _create_section_requests_for_submission(
            submission, target_section_ids, requested_by=admin_user,
        )

    sent_quote = (
        SettlementQuote.objects.filter(
            submission_id=submission_id,
            status=SettlementQuote.Status.FINAL_SENT,
            revision_superseded_at__isnull=True,
        )
        .order_by("-sent_at", "-updated_at")
        .first()
    )
    if sent_quote:
        sent_quote.revision_superseded_at = now
        sent_quote.save(update_fields=["revision_superseded_at"])

    conv = _get_or_create_shared_conversation(submission, subject_fallback="설문 수정 허용")
    sender = _pick_staff_sender(conv)
    cta_body = (
        "관리자가 설문 수정을 허용했습니다. 메시지함 또는 대시보드에서 '설문 수정하기' 버튼을 눌러 수정을 시작해 주세요."
    )
    if sender:
        create_customer_auto_reply(conv, cta_body, sender)

    return True, None, None


def get_submission_reopen_status(submission: Any) -> dict:
    """
    Admin UI용: 현재 submission 상태, 최신 quote/요청 상태, reopen 가능 여부, 마지막 reopen 시각, pending offer id.
    """
    from survey.models import SurveySubmission
    from settlement.models import CustomerActionOffer, QuoteChangeRequest, SettlementQuote

    out = {
        "submission_status": getattr(submission, "status", None),
        "submission_status_display": getattr(submission, "get_status_display", lambda: "")(),
        "latest_quote_status": None,
        "latest_quote_id": None,
        "latest_request_status": None,
        "latest_change_request_id": None,
        "can_admin_initiate_reopen": False,
        "pending_reopen_offer_id": None,
        "last_reopen_at": None,
    }
    if not submission or not getattr(submission, "id", None):
        return out

    sub_id = submission.id
    status = getattr(submission, "status", None)
    out["last_reopen_at"] = getattr(submission, "reopened_at", None) or getattr(submission, "revision_requested_at", None)

    pending = CustomerActionOffer.objects.filter(
        submission_id=sub_id,
        button_action_key="reopen_survey",
        status=CustomerActionOffer.Status.PENDING,
    ).first()
    if pending:
        out["pending_reopen_offer_id"] = pending.id
    out["can_admin_initiate_reopen"] = (
        status in (SurveySubmission.Status.SUBMITTED, SurveySubmission.Status.AWAITING_PAYMENT)
        and not out["pending_reopen_offer_id"]
    )

    latest_quote = (
        SettlementQuote.objects.filter(submission_id=sub_id)
        .order_by("-updated_at")
        .values("id", "status")
        .first()
    )
    if latest_quote:
        out["latest_quote_id"] = latest_quote["id"]
        out["latest_quote_status"] = latest_quote.get("status")

    latest_cr = QuoteChangeRequest.objects.filter(submission_id=sub_id).order_by("-created_at").values("id", "status").first()
    if latest_cr:
        out["latest_change_request_id"] = latest_cr["id"]
        out["latest_request_status"] = latest_cr.get("status")

    return out


def build_customer_ui_payload(
    user: Any,
    *,
    conversation: Optional[Any] = None,
    submission: Optional[Any] = None,
    quote: Optional[Any] = None,
) -> dict:
    """
    고객 UI 통합 payload. 메시지함/대시보드/견적 화면에서 동일한 상태·액션을 보여주기 위한 서버 truth.
    CustomerActionProposal(신규) + CustomerActionOffer(레거시) 통합 조회.
    반환: pending_actions, action_offers, review_status, execution_mode, can_reopen_survey,
          can_resume_survey, can_resend_quote, current_request_status
    """
    from survey.models import SurveySubmission
    from settlement.models import (
        CustomerActionOffer,
        HumanReviewRequest,
        QuoteChangeRequest,
        SettlementQuote,
    )
    from messaging.models import CustomerActionProposal

    out: Dict[str, Any] = {
        "pending_actions": [],
        "action_offers": [],
        "review_status": {"has_review": False, "status": "", "review_id": None, "message": ""},
        "execution_mode": "",
        "can_reopen_survey": False,
        "can_resume_survey": False,
        "can_resend_quote": False,
        "current_request_status": "",
    }
    if not user or not getattr(user, "id", None):
        return out

    sub = submission
    if not sub and quote and getattr(quote, "submission_id", None):
        sub = SurveySubmission.objects.filter(id=quote.submission_id).first()
    if not sub and conversation and getattr(conversation, "survey_submission_id", None):
        sub = SurveySubmission.objects.filter(id=conversation.survey_submission_id).first()
    if not sub and not conversation:
        sub = (
            SurveySubmission.objects.filter(user=user)
            .exclude(status=SurveySubmission.Status.DRAFT)
            .order_by("-updated_at")
            .first()
        )

    # -- 신규: CustomerActionProposal 조회 --
    prop_qs = CustomerActionProposal.objects.filter(
        analysis__customer=user,
    ).order_by("-created_at")
    if conversation and getattr(conversation, "id", None):
        prop_qs = prop_qs.filter(conversation_id=conversation.id)
    if sub:
        prop_qs = prop_qs.filter(submission_id=sub.id)
    proposals = list(prop_qs[:20])

    _STATUS_MAP_PROPOSAL = {
        CustomerActionProposal.Status.PROPOSED: "PENDING",
        CustomerActionProposal.Status.CONFIRMED: "PENDING",
        CustomerActionProposal.Status.EXECUTED: "EXECUTED",
        CustomerActionProposal.Status.DECLINED: "EXPIRED",
        CustomerActionProposal.Status.EXPIRED: "EXPIRED",
        CustomerActionProposal.Status.FAILED: "EXPIRED",
    }

    for p in proposals:
        compat_status = _STATUS_MAP_PROPOSAL.get(p.status, "PENDING")
        item = {
            "id": p.id,
            "proposal_id": p.id,
            "title": (p.title or "")[:200],
            "body": (p.body or "")[:500],
            "button_label": _default_button_label_for_code(p.action_code),
            "decline_label": _proposal_decline_label(p.action_code),
            "button_action_key": p.action_code or "",
            "status": compat_status,
            "can_execute": p.status == CustomerActionProposal.Status.PROPOSED,
            "executed_at": p.executed_at.isoformat() if p.executed_at else None,
            "execution_mode": "AUTO_CONFIRMABLE",
            "created_at": p.analysis.created_at.isoformat() if p.analysis and p.analysis.created_at else None,
            "request_id": getattr(p.analysis, "request_id", None) or "",
        }
        out["action_offers"].append(item)
        if p.status == CustomerActionProposal.Status.PROPOSED:
            out["pending_actions"].append(item)

    # -- 레거시: CustomerActionOffer 조회 (DB에 남아있는 이전 오퍼) --
    offer_qs = CustomerActionOffer.objects.filter(submission__user=user).order_by("-created_at")
    if conversation and getattr(conversation, "id", None):
        offer_qs = offer_qs.filter(conversation_id=conversation.id)
    if sub:
        offer_qs = offer_qs.filter(submission_id=sub.id)
    offers = list(offer_qs[:20])
    for o in offers:
        item = {
            "id": o.id,
            "title": (o.title or "")[:200],
            "body": (o.body or "")[:500],
            "button_label": o.button_label or "",
            "button_action_key": o.button_action_key or "",
            "status": o.status,
            "can_execute": bool(o.can_execute),
            "executed_at": o.executed_at.isoformat() if o.executed_at else None,
            "execution_mode": "AUTO_CONFIRMABLE",
            "request_id": "",
        }
        out["action_offers"].append(item)
        if o.status == CustomerActionOffer.Status.PENDING:
            out["pending_actions"].append(item)

    # Human review
    from django.db.models import Q
    review_qs = (
        HumanReviewRequest.objects.filter(
            Q(conversation__participants__user=user) | Q(submission__user=user)
        )
        .exclude(status=HumanReviewRequest.Status.COMPLETED)
        .order_by("-created_at")
        .distinct()
    )
    if conversation and getattr(conversation, "id", None):
        review_qs = review_qs.filter(conversation_id=conversation.id)
    if sub:
        review_qs = review_qs.filter(submission_id=sub.id)
    rev = review_qs.first()
    if rev:
        status_label = {
            HumanReviewRequest.Status.RECEIVED: "접수됨",
            HumanReviewRequest.Status.IN_REVIEW: "검토 중",
            HumanReviewRequest.Status.NEEDS_INFO: "추가 확인 필요",
        }.get(rev.status, rev.get_status_display() or rev.status)
        out["review_status"] = {
            "has_review": True,
            "status": rev.status,
            "review_id": rev.id,
            "message": status_label,
        }
        out["execution_mode"] = "HUMAN_REVIEW_REQUIRED"

    if sub and getattr(sub, "user_id", None) == getattr(user, "id", None):
        st = getattr(sub, "status", None)
        out["can_reopen_survey"] = st == SurveySubmission.Status.REVISION_REQUESTED
        out["can_resume_survey"] = out["can_reopen_survey"]

    if sub:
        sent = (
            SettlementQuote.objects.filter(
                submission=sub,
                status=SettlementQuote.Status.FINAL_SENT,
                revision_superseded_at__isnull=True,
            )
            .order_by("-sent_at")
            .first()
        )
        has_pending_resend = any(
            a.get("button_action_key") == "resend_quote"
            and a.get("status") == "PENDING"
            for a in out["action_offers"]
        )
        out["can_resend_quote"] = bool(sent) or has_pending_resend

    if sub:
        cr = (
            QuoteChangeRequest.objects.filter(submission=sub)
            .order_by("-created_at")
            .values("id", "status")
            .first()
        )
        if cr:
            status_map = {
                QuoteChangeRequest.Status.OPEN: "요청 접수됨",
                QuoteChangeRequest.Status.ANALYZED: "검토 중",
                QuoteChangeRequest.Status.IN_REVIEW: "검토 중",
                QuoteChangeRequest.Status.APPROVED: "새 견적 준비 중",
                QuoteChangeRequest.Status.CUSTOMER_ACTION_REQUIRED: "고객 확인 필요",
                QuoteChangeRequest.Status.APPLIED: "완료",
                QuoteChangeRequest.Status.REJECTED: "반려됨",
                QuoteChangeRequest.Status.CANCELED: "취소됨",
            }
            out["current_request_status"] = status_map.get(cr["status"], cr.get("status") or "")
        if out["review_status"]["has_review"] and not out["current_request_status"]:
            out["current_request_status"] = out["review_status"]["message"]
        if out["can_reopen_survey"] and not out["current_request_status"]:
            out["current_request_status"] = "설문 수정 가능"

    return out


def create_customer_auto_reply(
    conversation: Any,
    body: str,
    sender: Any,
    *,
    detect_lang: bool = True,
) -> Optional[Any]:
    """고객에게 보낼 자동 응답 메시지 1건 생성·저장. 반환: Message 또는 None."""
    from messaging.models import Message, MessageRead

    if not conversation or not sender or not body:
        return None
    msg = Message(conversation=conversation, sender=sender, body=body)
    if detect_lang:
        try:
            from messaging.views import _detect_and_translate_to_en
            msg.detected_lang, msg.body_en = _detect_and_translate_to_en(body)
        except Exception:
            pass
    msg.save()
    MessageRead.objects.get_or_create(message=msg, user=sender)
    conversation.updated_at = timezone.now()
    conversation.save(update_fields=["updated_at"])
    return msg


def sync_related_submission_quote_state(
    submission: Any,
    *,
    revision_requested: bool = False,
    supersede_sent_quote: bool = False,
    now: Optional[Any] = None,
) -> None:
    """
    설문 재개 등 실행 시 연관 submission·quote 상태 동기화.
    execute_confirmed_action 내부에서 호출하거나, Admin 승인 플로우에서 재사용.
    """
    if now is None:
        now = timezone.now()
    if revision_requested and submission:
        from survey.models import SurveySubmission
        submission.status = SurveySubmission.Status.REVISION_REQUESTED
        submission.revision_requested_at = now
        submission.save(update_fields=["status", "revision_requested_at", "updated_at"])
    if supersede_sent_quote and submission:
        from settlement.models import SettlementQuote
        sent = (
            SettlementQuote.objects.filter(
                submission=submission,
                status=SettlementQuote.Status.FINAL_SENT,
            ).order_by("-sent_at", "-updated_at").first()
        )
        if sent:
            sent.revision_superseded_at = now
            sent.save(update_fields=["revision_superseded_at"])


def handle_customer_request_flow(
    channel: str,
    user: Any,
    text: str,
    *,
    conversation: Optional[Any] = None,
    message: Optional[Any] = None,
    quote: Optional[Any] = None,
) -> RequestFlowResult:
    """
    통합 흐름: intake → analyze → 분류 저장 → 제안/라우팅 → 자동 응답.

    모든 경로에서 CustomerRequestIntentAnalysis 를 먼저 저장.
    - AUTO_CONFIRMABLE: CustomerActionProposal 생성 (즉시 실행 없음). 고객 확인 후 confirm_proposal()로 실행.
    - HUMAN_REVIEW_REQUIRED: HumanReviewRequest 라우팅 유지.
    - REPLY_ONLY: 자동 응답만.

    반환: RequestFlowResult (analysis, proposal, 확인 필요 여부, 사람 검토 여부).
    """
    from customer_request_policy import ExecutionMode

    # 최근 제안에 대한 정정 감지 (분류 전에 실행)
    if conversation and text:
        try:
            detect_and_record_correction(conversation, text, user)
        except Exception:
            logger.debug("correction detection failed (non-critical)", exc_info=True)

    ctx = intake_customer_request(
        channel, user, text,
        conversation=conversation, message=message, quote=quote,
    )
    if not ctx:
        return RequestFlowResult(error="요청을 접수할 수 없습니다.")

    classification = analyze_customer_request(ctx)
    if classification is None:
        return RequestFlowResult(error="요청을 분류할 수 없습니다.")
    policy = classification.policy
    request_id = uuid.uuid4().hex

    analysis_record = _save_intent_analysis(
        ctx,
        policy,
        request_id=request_id,
        classification=classification,
    )

    conv = ctx.conversation
    staff_sender = _pick_staff_sender(conv)
    auto_reply_body = (policy.customer_facing_summary or "").strip() or "요청을 확인했습니다. 검토 후 안내드리겠습니다."

    result = RequestFlowResult(ctx=ctx, policy=policy, analysis=analysis_record, request_id=request_id)

    try:
        from messaging.feedback_events import log_message_received, log_route_predicted

        log_message_received(
            request_id,
            user_id=getattr(ctx.user, "id", None),
            survey_submission_id=getattr(ctx.submission, "id", None) if ctx.submission else None,
            message_text=(ctx.text or "")[:2000],
        )
        log_route_predicted(
            request_id,
            user_id=getattr(ctx.user, "id", None),
            survey_submission_id=getattr(ctx.submission, "id", None) if ctx.submission else None,
            user_message=getattr(classification, "user_message", "") or (ctx.text or ""),
            heuristic_result=getattr(classification, "heuristic_result", None),
            llm_result=getattr(classification, "llm_result", None),
            merged_candidates=getattr(classification, "merged_candidates", None),
            selected_primary_page=getattr(classification, "selected_primary_page", None),
            recommendation_confidence=getattr(classification, "recommendation_confidence", None),
        )
    except Exception:
        logger.warning("feedback event logging failed request_id=%s", request_id, exc_info=True)

    if policy.execution_mode == ExecutionMode.AUTO_CONFIRMABLE and policy.should_create_action_offer:
        proposal = _create_action_proposal(analysis_record, ctx, policy)

        if proposal and getattr(policy, "target_section_ids", None) and ctx.submission:
            _create_section_requests_for_submission(
                ctx.submission, policy.target_section_ids, requested_by=user,
            )
        if proposal:
            guide = _proposal_guide_message(proposal.action_code)
            auto_reply_body = guide or auto_reply_body
            result.proposal = proposal
            result.should_require_user_confirmation = True
        if staff_sender:
            reply_msg = create_customer_auto_reply(conv, auto_reply_body, staff_sender)
            _attach_feedback_target_message(analysis_record, reply_msg)

    elif policy.execution_mode == ExecutionMode.HUMAN_REVIEW_REQUIRED:
        route_request_for_human_review(ctx, policy)
        result.should_route_to_human_review = True
        if staff_sender:
            body = _human_review_auto_reply_body("RECEIVED", policy)
            reply_msg = create_customer_auto_reply(conv, body, staff_sender)
            _attach_feedback_target_message(analysis_record, reply_msg)
    else:
        if staff_sender:
            reply_msg = create_customer_auto_reply(conv, auto_reply_body, staff_sender)
            _attach_feedback_target_message(analysis_record, reply_msg)

    return result


def _pick_staff_sender(conversation: Any):
    """자동 응답 발신자로 쓸 staff 사용자."""
    if not conversation:
        return None
    from messaging.models import ConversationParticipant
    from django.contrib.auth import get_user_model
    User = get_user_model()
    cp = (
        ConversationParticipant.objects.filter(conversation=conversation, user__is_staff=True)
        .select_related("user")
        .order_by("id")
        .first()
    )
    if cp:
        return cp.user
    return User.objects.filter(is_staff=True).order_by("-is_superuser", "id").first()


def _default_button_label_for_code(action_code: str) -> str:
    """action_code 기반 버튼 라벨. 정책 테이블에서 조회."""
    from customer_request_policy import get_policy_for_action_code
    entry = get_policy_for_action_code((action_code or "").strip())
    return entry.button_label if entry else "진행하기"


def _proposal_guide_message(action_code: str) -> str:
    """action_code별 고객에게 보여줄 안내 메시지. 정책 테이블에서 조회."""
    from customer_request_policy import get_policy_for_action_code
    entry = get_policy_for_action_code((action_code or "").strip())
    return entry.guide_message if entry else ""


def _proposal_decline_label(action_code: str) -> str:
    """action_code별 거절/취소 버튼 라벨."""
    return "취소"


# ---------------------------------------------------------------------------
# 학습 신호(Learning Signal) — 후속 행동 / 정정 감지
# ---------------------------------------------------------------------------

_RE_CORRECTION = re.compile(
    r"(그게\s*아니|아니[요요에]|잘못|틀렸|다른\s*거|원래|사실\s*은|아\s*닙니다|맞지\s*않|아닌데|"
    r"that's\s*not|not\s*what\s*i\s*(meant|wanted)|wrong|actually\s*i\s*(want|need)|"
    r"instead\s*of|no\s*i\s*mean|sorry\s*i\s*meant)",
    re.I,
)

_FOLLOWUP_PROPOSAL_STATUSES = frozenset({"PROPOSED", "CONFIRMED", "EXECUTED"})

_FOLLOWUP_LOOKBACK_MINUTES = 120


def record_followup_success(
    submission: Any,
    *,
    event_meta: Optional[dict] = None,
) -> Optional[Any]:
    """
    고객이 실제 후속 행동을 완료했을 때 호출 (예: survey resubmit).
    가장 최근 EXECUTED reopen_survey proposal 에 FOLLOWUP_SUCCESS 로그 기록.
    """
    from messaging.models import CustomerActionProposal
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(hours=48)

    proposal = (
        CustomerActionProposal.objects
        .filter(
            submission=submission,
            action_code="reopen_survey",
            status=CustomerActionProposal.Status.EXECUTED,
            executed_at__gte=cutoff,
        )
        .select_related("analysis")
        .order_by("-executed_at")
        .first()
    )
    if not proposal:
        return None

    from messaging.models import CustomerActionFeedbackLog
    already = CustomerActionFeedbackLog.objects.filter(
        proposal=proposal,
        event_type="FOLLOWUP_SUCCESS",
    ).exists()
    if already:
        return None

    payload = _build_learning_signal(
        proposal, "confirmed", final_outcome="success",
        extra={
            "followup_event": "survey_resubmitted",
            **(event_meta or {}),
        },
    )
    return _log_feedback(proposal, "FOLLOWUP_SUCCESS", payload=payload)


def detect_and_record_correction(
    conversation: Any,
    text: str,
    user: Any,
) -> Optional[Any]:
    """
    고객의 새 메시지가 최근 제안에 대한 정정("그게 아니라 …")인지 감지.
    correction 패턴 매칭 시 USER_CORRECTED 이벤트를 기록하고 해당 proposal 반환.
    """
    s = (text or "").strip()
    if not s or not conversation:
        return None

    if not _RE_CORRECTION.search(s):
        return None

    from messaging.models import CustomerActionProposal
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(minutes=_FOLLOWUP_LOOKBACK_MINUTES)

    recent_proposal = (
        CustomerActionProposal.objects
        .filter(
            conversation=conversation,
            status__in=list(_FOLLOWUP_PROPOSAL_STATUSES),
            created_at__gte=cutoff,
        )
        .select_related("analysis")
        .order_by("-created_at")
        .first()
    )
    if not recent_proposal:
        return None

    from messaging.models import CustomerActionFeedbackLog
    already = CustomerActionFeedbackLog.objects.filter(
        proposal=recent_proposal,
        event_type="USER_CORRECTED",
    ).exists()
    if already:
        return None

    payload = _build_learning_signal(
        recent_proposal, "corrected",
        followup_text=s,
        extra={"correction_detected_by": "heuristic_regex"},
    )
    _log_feedback(recent_proposal, "USER_CORRECTED", actor=user, payload=payload)

    logger.info(
        "correction detected: proposal_id=%s conversation_id=%s text_preview=%s",
        recent_proposal.id,
        getattr(conversation, "id", "?"),
        s[:80],
    )

    return recent_proposal
