"""
견적 초안 자동 생성.
설문 제출(SurveySubmission)의 정규화된 답변으로 SettlementQuote DRAFT를 생성·갱신합니다.

자동화되는 것:
- 제출에서 get_quote_input_data()로 service_codes, add_on_codes, region 등 추출
- service_codes/add_on_codes → SettlementService 조회 후 items 생성 (code, label, price)
- DB에 매칭되는 서비스는 customer_price로 가격 채움, 합계(total) 자동 계산
- 매칭 안 되는 코드는 항목만 추가하고 price=0, _needs_review=True로 Admin 검토 유도
- draft_source='auto', auto_generated_at 기록으로 "자동 생성 draft" 구분

Admin 검토가 필요한 것:
- _needs_review=True인 항목(미등록 코드 또는 수동 가격)
- region/entry_date 등 추가 반영 여부(현재는 region만 반영)
- 할인·패키지·지역별 가격 등 복잡 규칙은 추후 pricing 모듈에서 적용

향후 가격 규칙 위치:
- 단순 코드별 단가는 SettlementService.customer_price 유지
- 지역/가구원/패키지 할인 등은 settlement/pricing.py(신규)에서 규칙 정의 후
  generate_quote_draft_from_submission() 또는 별도 build_quote_items()에서 호출하도록 확장
"""
import logging
from decimal import Decimal
from django.utils import timezone

logger = logging.getLogger(__name__)

# items 항목에 넣는 메타 키 (고객 노출 시 제거 가능)
ITEM_KEY_AUTO = '_auto'
ITEM_KEY_NEEDS_REVIEW = '_needs_review'


def generate_quote_draft_from_submission(submission, actor=None):
    """
    제출에서 견적 DRAFT 생성 또는 갱신.
    - 정규화된 답변(get_quote_input_data)으로 region, items, total 채움.
    - service_codes/add_on_codes → SettlementService로 조회해 항목 생성. 매칭 실패 시 가격 0 + _needs_review.
    - 기존 DRAFT가 있으면 갱신, 없으면 생성. FINAL_SENT/PAID 견적은 건드리지 않음.
    - actor: 로그용 (User 또는 None). 현재는 저장하지 않음.
    Returns: (quote, created: bool) or (None, False) on error.
    """
    if not submission:
        return None, False
    from survey.quote_input import get_quote_input_data
    from .models import SettlementQuote, SettlementService
    from .constants import get_service_customer_price, _normalize_state_code

    data = get_quote_input_data(submission)
    service_codes = list(data.get('service_codes') or [])
    add_on_codes = list(data.get('add_on_codes') or [])
    all_codes = list(dict.fromkeys(service_codes + add_on_codes))  # 순서 유지, 중복 제거
    region = (data.get('region') or '').strip() or ''
    state_code = _normalize_state_code(data.get('settlement_state') or region or '')
    special_requirements = (data.get('special_requirements') or '').strip()

    # 기존 DRAFT 조회 (갱신 대상). 이미 송부/결제된 견적이 있으면 새 DRAFT를 만들지 않음(기존 견적서 유지).
    existing_draft = (
        SettlementQuote.objects.filter(submission=submission, status=SettlementQuote.Status.DRAFT)
        .order_by('-updated_at')
        .first()
    )
    if existing_draft:
        quote = existing_draft
        created = False
        next_version = (quote.version or 1) + 1
    else:
        # DRAFT가 없을 때: 결제 가능한 송부/결제 견적이 있으면 새 초안 생성하지 않음.
        # 무효화(revision_superseded_at)된 견적만 있으면 재제출 후 새 DRAFT 생성 허용.
        has_payable_sent_or_paid = SettlementQuote.objects.filter(
            submission=submission,
            status__in=(SettlementQuote.Status.FINAL_SENT, SettlementQuote.Status.PAID),
            revision_superseded_at__isnull=True,
        ).exists()
        if has_payable_sent_or_paid:
            logger.info("Quote draft skip: submission_id=%s already has payable FINAL_SENT/PAID quote.", submission.id)
            return None, False
        quote = SettlementQuote(
            submission=submission,
            status=SettlementQuote.Status.DRAFT,
            version=1,
            region=region,
            items=[],
            total=Decimal('0'),
        )
        created = True
        next_version = 1

    # 항목 구성: 코드별 SettlementService 조회 → items
    services_by_code = {}
    for s in SettlementService.objects.filter(is_active=True):
        key = (s.code or str(s.id)).strip()
        if key:
            services_by_code[key] = s
    items = []
    total = Decimal('0')
    for code in all_codes:
        code = (code or '').strip()
        if not code:
            continue
        service = services_by_code.get(code)
        if service:
            price = get_service_customer_price(code, state_code or None)
            item = {
                'code': code,
                'label': service.name or code,
                'price': int(price),
                ITEM_KEY_AUTO: True,
                ITEM_KEY_NEEDS_REVIEW: False,
            }
            total += price
        else:
            item = {
                'code': code,
                'label': code,
                'price': 0,
                ITEM_KEY_AUTO: True,
                ITEM_KEY_NEEDS_REVIEW: True,
            }
        items.append(item)

    quote.items = items
    quote.total = total
    quote.region = region
    quote.version = next_version
    quote.draft_source = 'auto'
    quote.auto_generated_at = timezone.now()
    if created:
        quote.save()
    else:
        quote.save(update_fields=['items', 'total', 'region', 'version', 'updated_at', 'draft_source', 'auto_generated_at'])

    if special_requirements and not any(
        isinstance(x, dict) and x.get('code') == '_special_requirements' for x in quote.items
    ):
        # 특별 요청은 항목으로 넣지 않고, Admin이 보는 메모용. 여기서는 items에 넣지 않아도 됨 (submission에 있음).
        pass

    try:
        submission.advance_case_stage(submission.CaseStage.QUOTE_PREPARING)
    except Exception:
        pass

    logger.info(
        "Quote draft %s from submission_id=%s codes=%s total=%s",
        'created' if created else 'updated',
        submission.id,
        all_codes,
        int(quote.total),
    )

    if created:
        try:
            from .notifications import send_quote_arrived_admin_notification
            lang = 'ko'
            if getattr(submission, 'user_id', None) and submission.user_id:
                u = submission.user
                lang = (getattr(u, 'preferred_language', None) or '').strip() or lang
            send_quote_arrived_admin_notification(quote, language_code=lang)
            # 고객 가독성: 공유 대화에는 견적 도착 메시지 추가하지 않음(고객은 '설문 제출·Admin 검토중' 안내만 보게 함)
        except Exception as e:
            logger.warning("Quote arrived admin notification failed: %s", e, exc_info=True)

    return quote, created


def create_draft_from_sent_quote(submission):
    """
    송부된 견적(FINAL_SENT/PAID)을 복사해 수정용 DRAFT를 생성.
    기존 DRAFT가 있으면 (기존 DRAFT, False) 반환(중복 생성 방지).
    Returns: (draft_quote, created: bool). 송부된 견적이 없으면 (None, False).
    """
    from decimal import Decimal
    from .models import SettlementQuote

    if not submission:
        return None, False
    sent_quote = (
        SettlementQuote.objects.filter(
            submission=submission,
            status__in=(SettlementQuote.Status.FINAL_SENT, SettlementQuote.Status.PAID),
        ).order_by('-sent_at', '-updated_at').first()
    )
    if not sent_quote:
        return None, False
    existing_draft = (
        SettlementQuote.objects.filter(
            submission=submission,
            status=SettlementQuote.Status.DRAFT,
        ).order_by('-updated_at').first()
    )
    if existing_draft:
        return existing_draft, False
    items = []
    for it in (sent_quote.items or []):
        if not isinstance(it, dict):
            continue
        item = {k: v for k, v in it.items() if k not in (ITEM_KEY_AUTO, ITEM_KEY_NEEDS_REVIEW)}
        items.append(item)
    next_version = (sent_quote.version or 1) + 1
    new_draft = SettlementQuote(
        submission=submission,
        status=SettlementQuote.Status.DRAFT,
        version=next_version,
        region=sent_quote.region or '',
        items=items,
        total=sent_quote.total or Decimal('0'),
        draft_source='admin',
    )
    new_draft.save()
    logger.info("Quote draft created from sent quote: submission_id=%s draft_id=%s", submission.id, new_draft.id)
    return new_draft, True


def get_items_for_display(quote, strip_meta=True):
    """
    고객/이메일 노출용 items. _auto, _needs_review 제거.
    """
    if not quote or not quote.items:
        return []
    out = []
    for it in quote.items:
        if not isinstance(it, dict):
            continue
        item = dict(it)
        if strip_meta:
            item.pop(ITEM_KEY_AUTO, None)
            item.pop(ITEM_KEY_NEEDS_REVIEW, None)
        out.append(item)
    return out
