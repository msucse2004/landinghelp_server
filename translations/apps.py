from django.apps import AppConfig


class TranslationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'translations'
    verbose_name = '고정 번역(CSV)'

    def ready(self):
        import translations.signals  # noqa: F401 - Admin 저장/삭제 시 캐시 갱신

        """gettext 래핑: DB에 있으면 그 값, 없으면 DeepL로 번역 후 DB 저장하고 반환, 실패 시 .po."""
        from django.utils import translation
        from translations.utils import get_from_cache
        from translations.services import get_or_translate_with_deepl

        _orig_gettext = translation.gettext

        def gettext_with_static(key):
            if not key:
                return ''
            lang = translation.get_language()
            value = get_from_cache(key, lang)
            if value is not None and str(value).strip():
                return value
            try:
                value = get_or_translate_with_deepl(key, lang)
                if value:
                    return value
            except Exception:
                pass
            return _orig_gettext(key)

        translation.gettext = gettext_with_static
