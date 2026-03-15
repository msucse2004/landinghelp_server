import json
from django import template

register = template.Library()


@register.filter
def get_item(d, key):
    """딕셔너리에서 키로 값 조회. 없으면 빈 문자열."""
    if d is None:
        return ''
    return d.get(key, '')


@register.filter
def in_list(val, lst):
    """값이 리스트에 있으면 True."""
    return val in (lst or [])


@register.filter
def json_dumps(val):
    """리스트/딕셔너리를 JSON 문자열로."""
    if val is None:
        return '[]'
    try:
        return json.dumps(val)
    except (TypeError, ValueError):
        return '[]'
