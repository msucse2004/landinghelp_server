"""
관리자가 추가한 텍스트를 키로 하여 지원 모든 언어로 번역 후 StaticTranslation(CSV)에 저장.
DeepL API 사용 (키 없으면 번역 건너뜀).
"""
import logging

from django.conf import settings

from .utils import (
    get_supported_language_codes,
    get_from_cache,
    save_translation_from_api,
    ensure_static_translation_key,
    _has_hangul,
)

logger = logging.getLogger(__name__)

# settings.LANGUAGES 코드 -> DeepL API target 언어 코드 (EN 대신 EN-US 사용, deprecated 방지)
LANG_TO_DEEPL = {
    'ko': 'KO',
    'en': 'EN-US',
    'zh-hans': 'ZH-HANS',
    'zh-hant': 'ZH-HANT',
    'vi': 'VI',
    'es': 'ES',
}


def _get_deepl_translator():
    """DeepL 번역기. API 키 없으면 None."""
    import os
    auth_key = (getattr(settings, 'DEEPL_AUTH_KEY', None) or os.environ.get('DEEPL_AUTH_KEY') or '').strip()
    if not auth_key:
        return None
    try:
        import deepl
        return deepl.Translator(auth_key)
    except Exception as e:
        logger.warning('DeepL 초기화 실패: %s', e)
        return None


def _translate_one(translator, text: str, target_deepl: str, source_deepl: str = 'KO') -> str:
    """한 문장 번역."""
    if not text or not text.strip():
        return ''
    try:
        result = translator.translate_text(
            text,
            source_lang=source_deepl,
            target_lang=target_deepl,
            preserve_formatting=True,
        )
        return (result.text or '').strip()
    except Exception as e:
        logger.warning('DeepL 번역 실패 (%s -> %s): %s', source_deepl, target_deepl, e)
        return ''


def translate_and_save_to_static(key_text: str, source_lang: str = 'ko') -> bool:
    """
    관리자가 입력한 문구(key_text)를 고정 번역에 등록하고,
    지원하는 모든 언어로 번역해 StaticTranslation(CSV)에 저장.
    같은 단어면 한글 키를 사용(ensure_static_translation_key).
    source_lang: 입력 문구의 언어(기본 ko). 해당 언어는 원문 그대로 저장.
    DeepL 키가 없으면 원문만 source_lang으로 저장하고 True 반환.
    """
    key_text = (key_text or '').strip()
    if len(key_text) < 1:
        return False
    supported = get_supported_language_codes()
    if source_lang not in supported:
        source_lang = supported[0] if supported else 'ko'

    # 동일 문구면 한글 키로 통일 (기존 행이 있으면 그 key 사용)
    canonical_key = ensure_static_translation_key(key_text, source_lang)
    if not canonical_key:
        return False

    # 원문을 source_lang 컬럼에 저장 (이미 ensure에서 처리했을 수 있음)
    save_translation_from_api(canonical_key, source_lang, key_text)

    source_deepl = LANG_TO_DEEPL.get(source_lang, 'KO')
    translator = _get_deepl_translator()

    for lang in supported:
        if lang == source_lang:
            continue
        existing = get_from_cache(canonical_key, lang)
        if existing:
            continue
        if translator:
            target_deepl = LANG_TO_DEEPL.get(lang)
            if not target_deepl:
                continue
            translated = _translate_one(translator, key_text, target_deepl, source_deepl)
            if translated:
                save_translation_from_api(canonical_key, lang, translated)
        else:
            save_translation_from_api(canonical_key, lang, key_text)
    return True


def get_or_translate_with_deepl(key: str, target_lang: str) -> str:
    """
    DB에 번역이 있으면 반환, 없으면 DeepL로 번역 후 DB 저장하고 반환.
    항상 DB 조회를 먼저 하고, 없을 때만 DeepL 호출.
    """
    if not key or not (key := (key or '').strip()):
        return ''
    supported = get_supported_language_codes()
    if target_lang not in supported:
        target_lang = supported[0] if supported else 'ko'

    existing = get_from_cache(key, target_lang)
    if existing is not None and str(existing).strip():
        return str(existing).strip()

    if target_lang == 'ko':
        return key

    canonical_key = ensure_static_translation_key(key, 'ko')
    if not canonical_key:
        return key

    translator = _get_deepl_translator()
    if not translator:
        return key

    target_deepl = LANG_TO_DEEPL.get(target_lang)
    if not target_deepl:
        return key

    source_deepl = 'KO' if _has_hangul(key) else 'EN-US'
    translated = _translate_one(translator, key, target_deepl, source_deepl)
    if translated:
        save_translation_from_api(canonical_key, target_lang, translated)
        return translated
    return key
