"""
고정 번역: utils 캐시(StaticTranslation)에 있으면 사용, 없으면 gettext 폴백.
사용: {% load trans_fixed %} ... {% trans_fixed "로그아웃" %}
"""
from django import template
from django.utils import translation

register = template.Library()


def get_static_translation(key: str, language_code: str | None = None) -> str | None:
    """key에 대한 language_code 번역. utils 캐시 사용(단일 경로). 없으면 None."""
    if not key:
        return None
    from translations.utils import get_from_cache
    lang = language_code or translation.get_language() or 'en'
    return get_from_cache(key.strip(), lang)


@register.simple_tag
def trans_fixed(key: str) -> str:
    """고정 번역: 캐시에 있으면 그 값, 없으면 gettext(key)."""
    if not key:
        return ''
    from translations.utils import get_from_cache
    lang = translation.get_language() or 'en'
    val = get_from_cache(key.strip(), lang)
    if val is not None and str(val).strip():
        return str(val).strip()
    with translation.override(lang):
        return translation.gettext(key)
