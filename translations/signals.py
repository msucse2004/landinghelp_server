from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import StaticTranslation, LANG_CODE_TO_FIELD
from .utils import update_cache_entry, remove_cache_entry


@receiver(post_save, sender=StaticTranslation)
def static_translation_saved(sender, instance, **kwargs):
    """Admin/API에서 저장 시 해당 key의 모든 언어 값을 캐시에 반영."""
    lang_values = {}
    for lang_code, field_name in LANG_CODE_TO_FIELD.items():
        val = getattr(instance, field_name, None) or ''
        if val:
            lang_values[lang_code] = val
    if not lang_values and instance.key:
        lang_values['ko'] = (instance.key or '').strip()
    update_cache_entry((instance.key or '').strip(), lang_values)


@receiver(post_delete, sender=StaticTranslation)
def static_translation_deleted(sender, instance, **kwargs):
    """삭제 시 해당 key를 캐시에서 제거."""
    remove_cache_entry((instance.key or '').strip())
