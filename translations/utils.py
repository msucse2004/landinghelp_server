"""
고정 번역 캐시(해시 테이블): key -> { language_code -> value }
DB 조회 없이 현재 언어의 번역을 반환하고, 번역 API 사용 시 여기와 CSV 테이블에 저장.
"""
import re
import threading

from django.conf import settings
from django.db.models import Q


# key(원문) -> { language_code -> 번역문 }
_translation_cache = {}
_cache_lock = threading.Lock()
_cache_loaded = False


def get_supported_language_codes():
    """settings.LANGUAGES 기준 지원 언어 코드 목록."""
    return [code for code, _ in getattr(settings, 'LANGUAGES', [])]


def _has_hangul(text: str) -> bool:
    """문자열에 한글이 포함되어 있으면 True."""
    if not text:
        return False
    return bool(re.search(r'[\uac00-\ud7a3]', str(text)))


def ensure_static_translation_key(text: str, source_lang: str = 'ko') -> str:
    """
    관리자가 추가한 문구를 고정 번역 키로 등록. 같은 단어면 한글 키를 사용.
    - 한글 포함 시: key=text 로 행 생성/유지, ko=text 설정 후 반환.
    - 한글 미포함 시: 이미 어떤 행의 언어 컬럼에 text가 있으면 그 행의 key(한글 우선) 반환;
      없으면 key=text 로 행 생성 후 반환.
    """
    text = (text or '').strip()
    if not text:
        return ''
    from translations.models import StaticTranslation, LANG_COLUMNS, LANG_CODE_TO_FIELD
    if source_lang not in LANG_CODE_TO_FIELD:
        source_lang = 'ko'
    field_name = LANG_CODE_TO_FIELD[source_lang]

    if _has_hangul(text):
        obj, _ = StaticTranslation.objects.get_or_create(
            key=text,
            defaults={f: '' for f in LANG_COLUMNS},
        )
        if not getattr(obj, 'ko', ''):
            setattr(obj, 'ko', text)
            obj.save()
        return text

    # 한글이 없음: 이미 동일 문구가 다른 행의 언어 컬럼에 있으면 그 행의 key 사용(한글 키 우선)
    q = Q(ko=text) | Q(en=text) | Q(es=text) | Q(zh_hans=text) | Q(zh_hant=text) | Q(vi=text)
    existing = list(StaticTranslation.objects.filter(q).only('key'))
    if existing:
        for row in existing:
            if _has_hangul(row.key):
                return row.key
        return existing[0].key

    obj, _ = StaticTranslation.objects.get_or_create(
        key=text,
        defaults={f: '' for f in LANG_COLUMNS},
    )
    setattr(obj, field_name, text)
    obj.save()
    return obj.key


def _load_cache():
    """StaticTranslation 전체를 메모리로 로드. key -> { lang -> value } (wide 컬럼: ko, en, es, zh-hans, zh-hant, vi)"""
    global _translation_cache, _cache_loaded
    with _cache_lock:
        if _cache_loaded:
            return
        try:
            from translations.models import StaticTranslation, LANG_CODE_TO_FIELD
            cache = {}
            for row in StaticTranslation.objects.all():
                k = (row.key or '').strip()
                if not k:
                    continue
                cache[k] = {}
                for lang_code, field_name in LANG_CODE_TO_FIELD.items():
                    val = getattr(row, field_name, None) or ''
                    if val:
                        cache[k][lang_code] = val
                if 'ko' not in cache[k] or not cache[k]['ko']:
                    cache[k]['ko'] = k
            _translation_cache = cache
            _cache_loaded = True
        except Exception:
            _translation_cache = {}
            _cache_loaded = True


def _normalize_lang_for_cache(language_code: str) -> list:
    """캐시 조회용 언어 코드 후보 목록. Django가 'vi-vn', 'vi_VN' 등으로 넘기면 'vi'로 매칭."""
    if not language_code:
        return []
    code = (language_code or '').strip()
    candidates = [code]
    if '-' in code:
        candidates.append(code.split('-')[0].lower())
    if '_' in code:
        candidates.append(code.split('_')[0].lower())
    return list(dict.fromkeys(candidates))


def get_from_cache(key: str, language_code: str) -> str | None:
    """
    해시 테이블에서 key에 대한 language_code 번역 반환.
    없으면 None. 언어 코드는 정규화(vi-vn → vi 등) 후 조회.
    """
    if not key:
        return None
    key_clean = key.strip() if isinstance(key, str) else key
    if not key_clean:
        return None
    _load_cache()
    lang_candidates = _normalize_lang_for_cache(language_code)
    with _cache_lock:
        for k in (key_clean, key) if key_clean != key else (key_clean,):
            by_lang = _translation_cache.get(k)
            if by_lang:
                for lang in lang_candidates:
                    val = by_lang.get(lang)
                    if val is not None:
                        return val
        return None


def save_translation_from_api(key: str, language_code: str, value: str) -> None:
    """
    번역 API 결과를 StaticTranslation에 저장하고 메모리 캐시에 반영.
    wide 스키마: key당 한 행, 해당 언어 컬럼만 갱신.
    """
    if not key or not value:
        return
    from translations.models import LANG_CODE_TO_FIELD
    if language_code not in LANG_CODE_TO_FIELD:
        return
    field_name = LANG_CODE_TO_FIELD[language_code]
    try:
        from translations.models import StaticTranslation
        obj, _ = StaticTranslation.objects.get_or_create(
            key=key.strip(),
            defaults={f: '' for f in ['ko', 'en', 'es', 'zh_hans', 'zh_hant', 'vi']},
        )
        setattr(obj, field_name, value)
        obj.save()
        _load_cache()
        with _cache_lock:
            if obj.key not in _translation_cache:
                _translation_cache[obj.key] = {}
            _translation_cache[obj.key][language_code] = value
    except Exception:
        pass


def invalidate_cache():
    """캐시 초기화(다음 조회 시 DB에서 재로드). Admin CSV 대량 import 후 등."""
    global _cache_loaded, _translation_cache
    with _cache_lock:
        _cache_loaded = False
        _translation_cache = {}


def update_cache_entry(key: str, lang_values: dict | None = None) -> None:
    """
    캐시에 한 키 반영(시그널 등에서 호출).
    wide 스키마: lang_values는 { language_code -> value } (전체 또는 일부).
    """
    _load_cache()
    with _cache_lock:
        if key not in _translation_cache:
            _translation_cache[key] = {}
        if lang_values:
            _translation_cache[key].update(lang_values)


def remove_cache_entry(key: str, language_code: str | None = None) -> None:
    """캐시에서 한 키 제거(삭제 시). language_code는 wide 스키마에서는 미사용."""
    _load_cache()
    with _cache_lock:
        if key in _translation_cache:
            del _translation_cache[key]


def get_display_text(key_text: str, language_code: str | None = None) -> str:
    """
    해시 테이블에서 현재 언어에 맞는 표시 문구 반환.
    없으면 원문(key_text) 그대로 반환.
    language_code 미지정 시 Django translation.get_language() 사용.
    """
    if not key_text:
        return ''
    if language_code is None:
        from django.utils import translation
        language_code = translation.get_language() or 'ko'
    key_clean = (key_text or '').strip()
    value = get_from_cache(key_clean, language_code)
    if value is not None and str(value).strip():
        return value
    return key_clean or key_text


class DisplayKey:
    """
    CSV(StaticTranslation) 조회용 키. 표시 시점에 get_display_text(key)로 번역 반환.
    verbose_name, label 등에 사용. CSV export 시 key 컬럼에 이 값으로 번역 행 조회 가능.
    """
    def __init__(self, key: str):
        self.key = (key or '').strip()

    def __str__(self):
        try:
            return get_display_text(self.key, None)
        except Exception:
            return self.key or ''

    def __repr__(self):
        return f'DisplayKey({self.key!r})'


def enrich_objects_for_display(objects, field_names, language_code: str | None = None) -> None:
    """
    객체(또는 이터러블)의 지정 필드에 대해 _display 속성을 채움.
    language_code 미지정 시 translation.get_language()로 현재 활성 언어 사용.
    """
    if language_code is None:
        from django.utils import translation
        language_code = translation.get_language() or 'ko'
    for obj in objects:
        for name in field_names:
            raw = getattr(obj, name, None)
            display = get_display_text(str(raw or ''), language_code)
            setattr(obj, f'{name}_display', display)
