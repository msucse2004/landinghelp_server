"""
고정 번역: DB(StaticTranslation)에 있으면 그대로 사용, 없으면 gettext로 폴백.
사용: {% load trans_fixed %} ... {% trans_fixed "로그아웃" %}
"""
from django import template
from django.utils import translation
register = template.Library()


def get_static_translation(key: str, language_code: str | None = None) -> str | None:
    """
    key에 대한 language_code 번역이 StaticTranslation에 있으면 반환, 없으면 None.
    """
    if not key:
        return None
    try:
        from translations.models import StaticTranslation
        lang = language_code or translation.get_language()
        row = StaticTranslation.objects.filter(key=key, language_code=lang).values_list('value', flat=True).first()
        return row
    except Exception:
        return None


@register.simple_tag
def trans_fixed(key: str) -> str:
    """
    고정 번역: DB에 (key, 현재 언어)가 있으면 그 값, 없으면 gettext(key) 사용.
    """
    if not key:
        return ''
    lang = translation.get_language()
    static = get_static_translation(key, lang)
    if static is not None:
        return static
    # 폴백: Django gettext
    with translation.override(lang):
        return translation.gettext(key)
