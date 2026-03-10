"""
견적 결제 처리 공통 로직.
api_quote_checkout 등에서 호출. 상태 전이·플랜·구독을 한 곳에서 처리해 중복 제거.
"""
import logging
from decimal import Decimal

from django.conf import settings

logger = logging.getLogger(__name__)


def process_quote_payment(user, quote_id=None):
    """
    고객의 견적 결제 처리: quote PAID, submission AGENT_ASSIGNMENT, 이벤트, 플랜/태스크, 구독 업데이트.
    결제 URL은 quote에 묶이고, 이 뷰는 로그인한 user와 quote 소유권으로만 검증.

    user: 로그인한 User (고객). Agent는 결제 불가.
    quote_id: int 또는 None. None이면 해당 user의 최신 FINAL_SENT 견적 사용.

    Returns:
        (quote, None) 성공 시
        (None, error_message: str) 실패 시 (이미 결제, 견적 없음, 권한 등)
    """
    from .models import SettlementQuote, UserSettlementPlan
    from survey.models import SurveySubmission, SurveySubmissionEvent

    if quote_id is not None:
        quote = (
            SettlementQuote.objects.filter(
                id=quote_id,
                submission__user=user,
            )
            .select_related('submission')
            .first()
        )
    else:
        # 무효화 정책: revision_superseded_at 이 있는 견적은 결제 대상에서 제외( hard delete 하지 않음)
        quote = (
            SettlementQuote.objects.filter(
                submission__user=user,
                status=SettlementQuote.Status.FINAL_SENT,
                revision_superseded_at__isnull=True,
            )
            .order_by('-updated_at')
            .select_related('submission')
            .first()
        )

    if not quote:
        return None, '결제 가능한 견적이 없습니다.'
    if quote.status == SettlementQuote.Status.PAID:
        return None, '이미 결제되었습니다.'
    if quote.status != SettlementQuote.Status.FINAL_SENT:
        return None, '이 견적은 아직 결제할 수 없습니다.'
    # 수정 요청으로 무효화된 견적은 결제 차단(레코드는 삭제하지 않음)
    if not quote.is_payable():
        return None, '수정 요청으로 인해 기존 견적은 더 이상 결제할 수 없습니다. 수정된 설문 검토 후 새 견적이 발송됩니다.'

    # --- 상태 전이: quote PAID, submission AGENT_ASSIGNMENT (스케줄 준비 단계) ---
    quote.status = SettlementQuote.Status.PAID
    quote.save(update_fields=['status'])

    if quote.submission_id:
        sub = quote.submission
        if sub.status != SurveySubmission.Status.AGENT_ASSIGNMENT:
            sub.status = SurveySubmission.Status.AGENT_ASSIGNMENT
            sub.save(update_fields=['status'])
        SurveySubmissionEvent.objects.create(
            submission=sub,
            event_type=SurveySubmissionEvent.EventType.PAID,
            created_by=user,
        )

    # --- UserSettlementPlan 생성/갱신 (견적 항목 → 초기 스케줄, 합계) ---
    from .post_payment import build_initial_schedule_from_quote, ensure_plan_service_tasks
    schedule = build_initial_schedule_from_quote(quote)
    total_val = Decimal(str(quote.total or 0))
    region = (quote.region or '').strip()
    state = region
    city = ''
    if region and ',' in region:
        parts = [p.strip() for p in region.split(',', 1)]
        state = parts[0] or region
        city = parts[1] if len(parts) > 1 else ''
    plan, _ = UserSettlementPlan.objects.update_or_create(
        user=user,
        defaults={
            'state': state,
            'city': city,
            'entry_date': None,
            'service_schedule': schedule,
            'checkout_total': total_val,
        },
    )
    ensure_plan_service_tasks(plan, quote)

    # --- 구독 tier: 결제 시 스탠다드 이상 유지 ---
    from billing.models import Plan, Subscription
    active_sub = (
        user.subscriptions.filter(status=Subscription.Status.ACTIVE)
        .order_by('-started_at')
        .select_related('plan')
        .first()
    )
    if not active_sub or (active_sub.plan and getattr(active_sub.plan, 'code', None) == Plan.Code.C_BASIC):
        plan_standard = Plan.objects.filter(code=Plan.Code.C_STANDARD, is_active=True).first()
        if plan_standard:
            if active_sub:
                active_sub.status = Subscription.Status.CANCELED
                active_sub.save(update_fields=['status'])
            Subscription.objects.create(
                user=user,
                plan=plan_standard,
                status=Subscription.Status.ACTIVE,
            )

    return quote, None
