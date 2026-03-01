"""
번역: 1순위 Google, 2순위 DeepL. 실패 시 다음 엔진으로 시도.
"""
import json
import logging
import os
import urllib.error
import urllib.request

from django.conf import settings

from .utils import (
    get_supported_language_codes,
    get_from_cache,
    save_translation_from_api,
    ensure_static_translation_key,
    _has_hangul,
    set_last_translation_error,
)

logger = logging.getLogger(__name__)

# 우리 언어 코드 -> Google Cloud Translation v2 (ISO-639-1)
LANG_TO_GOOGLE = {
    'ko': 'ko',
    'en': 'en',
    'es': 'es',
    'zh-hans': 'zh-CN',
    'zh-hant': 'zh-TW',
    'vi': 'vi',
}

# 우리 언어 코드 -> DeepL API target 코드 (EN-US 등)
LANG_TO_DEEPL = {
    'ko': 'KO',
    'en': 'EN-US',
    'zh-hans': 'ZH-HANS',
    'zh-hant': 'ZH-HANT',
    'vi': 'VI',
    'es': 'ES',
}


def _get_google_api_key():
    """Google Cloud Translation API 키. 없으면 빈 문자열."""
    return (
        getattr(settings, 'GOOGLE_TRANSLATE_API_KEY', None)
        or os.environ.get('GOOGLE_TRANSLATE_API_KEY', '')
    ).strip()


def _translate_with_google(text: str, target_lang: str, source_lang: str = 'ko') -> str:
    """
    Google Cloud Translation v2 (Basic)로 한 문장 번역.
    GOOGLE_TRANSLATE_ENABLED가 False이거나 키가 없으면 빈 문자열(DeepL로 폴백).
    """
    if not text or not text.strip():
        return ''
    if not getattr(settings, 'GOOGLE_TRANSLATE_ENABLED', False):
        return ''
    key = _get_google_api_key()
    if not key:
        return ''
    target_google = LANG_TO_GOOGLE.get(target_lang)
    source_google = LANG_TO_GOOGLE.get(source_lang) or (source_lang or 'ko').replace('_', '-')
    if not target_google:
        return ''
    url = f'https://translation.googleapis.com/language/translate/v2?key={key}'
    body = json.dumps({
        'q': text,
        'source': source_google,
        'target': target_google,
        'format': 'text',
    }).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=body,
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        translations = (data or {}).get('data', {}).get('translations') or []
        if translations and isinstance(translations[0].get('translatedText'), str):
            return (translations[0]['translatedText'] or '').strip()
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, json.JSONDecodeError, KeyError) as e:
        logger.warning('Google 번역 실패 (%s -> %s): %s', source_lang, target_lang, e)
    return ''


def _get_deepl_translator():
    """DeepL 번역기. API 키 없으면 None. 실패 시 set_last_translation_error로 구체 원인 설정."""
    try:
        from config.deepl_env import get_deepl_auth_key
        auth_key = (get_deepl_auth_key() or '').strip()
    except Exception:
        auth_key = (getattr(settings, 'DEEPL_AUTH_KEY', None) or '').strip()
    if not auth_key:
        set_last_translation_error('DEEPL_AUTH_KEY missing (env and Windows registry)')
        return None
    try:
        import deepl
        return deepl.Translator(auth_key)
    except Exception as e:
        set_last_translation_error('DeepL init failed: %s' % (str(e)[:200],))
        logger.warning('DeepL 초기화 실패: %s', e)
        return None


def _translate_one_deepl(translator, text: str, target_deepl: str, source_deepl: str = 'KO') -> str:
    """DeepL로 한 문장 번역. 실패 시 빈 문자열. 429(rate limit) 시 1회 재시도."""
    if not text or not text.strip():
        return ''
    import time
    for attempt in range(2):
        try:
            result = translator.translate_text(
                text,
                source_lang=source_deepl,
                target_lang=target_deepl,
                preserve_formatting=True,
            )
            return (result.text or '').strip()
        except Exception as e:
            set_last_translation_error(str(e))
            err_msg = str(e).lower()
            # 429 Too Many Requests 또는 rate limit 메시지면 한 번만 재시도
            if attempt == 0 and ('429' in err_msg or 'too many' in err_msg or 'rate' in err_msg):
                time.sleep(1.0)
                continue
            logger.warning('DeepL 번역 실패 (%s -> %s): %s', source_deepl, target_deepl, e)
            return ''
    return ''


def _translate_one(text: str, target_lang: str, source_lang: str = 'ko') -> str:
    """
    1순위 Google, 2순위 DeepL로 번역. 둘 다 실패 시 빈 문자열.
    target_lang, source_lang은 우리 코드(ko, en, zh-hans 등).
    """
    # 1순위: Google
    out = _translate_with_google(text, target_lang, source_lang)
    if out:
        return out
    # 2순위: DeepL
    translator = _get_deepl_translator()
    if not translator:
        # 구체 원인은 _get_deepl_translator에서 set_last_translation_error로 이미 설정됨
        logger.warning('DeepL 번역 스킵: 키 없음 또는 초기화 실패.')
        return ''
    target_deepl = LANG_TO_DEEPL.get(target_lang)
    source_deepl = LANG_TO_DEEPL.get(source_lang, 'KO')
    if not target_deepl:
        return ''
    if not source_lang or source_lang == 'ko' or _has_hangul(text):
        source_deepl = 'KO'
    else:
        source_deepl = 'EN-US'
    return _translate_one_deepl(translator, text, target_deepl, source_deepl)


def translate_and_save_to_static(key_text: str, source_lang: str = 'ko') -> bool:
    """
    관리자가 입력한 문구(key_text)를 고정 번역에 등록하고,
    지원하는 모든 언어로 1순위 Google → 2순위 DeepL 로 번역해 StaticTranslation(CSV)에 저장.
    같은 단어면 한글 키를 사용(ensure_static_translation_key).
    source_lang: 입력 문구의 언어(기본 ko). 해당 언어는 원문 그대로 저장.
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

    for lang in supported:
        if lang == source_lang:
            continue
        existing = get_from_cache(canonical_key, lang)
        if existing:
            continue
        translated = _translate_one(key_text, lang, source_lang)
        if translated:
            save_translation_from_api(canonical_key, lang, translated)
        else:
            save_translation_from_api(canonical_key, lang, key_text)
    return True


def get_or_translate_with_deepl(key: str, target_lang: str) -> str:
    """
    DB에 번역이 있으면 반환, 없으면 1순위 Google → 2순위 DeepL 로 번역 후 DB 저장하고 반환.
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

    source_lang = 'ko' if _has_hangul(key) else 'en'
    translated = _translate_one(key, target_lang, source_lang)
    if translated:
        save_translation_from_api(canonical_key, target_lang, translated)
        return translated
    return key
