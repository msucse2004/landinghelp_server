"""견적 가격 비노출 정책: can_view_price가 False일 때 mask_price 필터로 '견적 후 공개' 반환."""
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

# 정책 문구 (템플릿에서 i18n으로 덮어쓸 수 있음)
PRICE_MASKED_LABEL = '견적 후 공개'


@register.filter
def usd_format(value):
    """USD 통화 표시: 천 단위 콤마 + 소수 둘째 자리(.00)."""
    if value is None:
        return '0.00'
    try:
        n = float(value)
        return f'{n:,.2f}'
    except (TypeError, ValueError):
        return str(value) if value != '' else '0.00'


@register.filter
def mask_price(value, can_show):
    """
    can_show가 False이면 가격 비노출 정책에 따라 '견적 후 공개' 반환.
    can_show가 True이면 value를 그대로 포맷(숫자면 천단위 콤마 등)해 반환.
    """
    if can_show:
        if value is None:
            return ''
        try:
            n = int(float(value))
            return mark_safe(f'{n:,}')
        except (TypeError, ValueError):
            return str(value) if value is not None else ''
    return mark_safe(PRICE_MASKED_LABEL)
