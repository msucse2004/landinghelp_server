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

# 요청 단위로 번역 실패한 키 목록 (팝업용). 스레드 로컬.
# failed_entries: [{'key': str, 'error': str}, ...]
_translation_failed_local = threading.local()

# 번역 API/서비스에서 실패 시 설정하는 마지막 에러 메시지 (같은 요청 내에서 다음 _set_translation_failed가 참조)
_last_translation_error_local = threading.local()


def _clear_translation_failed():
    _translation_failed_local.failed_entries = []
    try:
        _last_translation_error_local.value = None
    except Exception:
        pass


def set_last_translation_error(message: str | None) -> None:
    """번역 실패 시 서비스에서 호출. 다음 _set_translation_failed 호출 시 error로 사용."""
    _last_translation_error_local.value = (message or '').strip() or None


def get_last_translation_error() -> str | None:
    """현재 요청에서 마지막으로 설정된 번역 실패 에러 메시지."""
    return getattr(_last_translation_error_local, 'value', None)


def _set_translation_failed(key: str, error_code: str | None = None) -> None:
    """번역 실패 시 실패한 키와 에러 메시지(있으면)를 목록에 추가 (중복 제거)."""
    entries = getattr(_translation_failed_local, 'failed_entries', None)
    if entries is None:
        _translation_failed_local.failed_entries = []
        entries = _translation_failed_local.failed_entries
    key_clean = (key or '').strip()
    if not key_clean:
        return
    existing_keys = {e['key'] for e in entries}
    if key_clean not in existing_keys:
        error = (error_code or '').strip() or get_last_translation_error() or ''
        entries.append({'key': key_clean, 'error': error})


def get_translation_failed():
    """현재 요청에서 번역 실패가 있었으면 True."""
    entries = getattr(_translation_failed_local, 'failed_entries', None)
    return bool(entries)


def get_translation_failed_keys():
    """현재 요청에서 번역 실패한 키 목록 (하위 호환용)."""
    entries = getattr(_translation_failed_local, 'failed_entries', None)
    if entries is None:
        return []
    return [e['key'] for e in entries]


def get_translation_failed_entries():
    """현재 요청에서 번역 실패한 키·에러 목록 (팝업 표시용). [{'key': str, 'error': str}, ...]"""
    entries = getattr(_translation_failed_local, 'failed_entries', None)
    return list(entries) if entries is not None else []


def clear_translation_failed():
    """요청 시작 시 번역 실패 목록 초기화 (미들웨어에서 호출)."""
    _translation_failed_local.failed_entries = []
    try:
        _last_translation_error_local.value = None
    except Exception:
        pass


def get_supported_language_codes():
    """settings.LANGUAGES 기준 지원 언어 코드 목록."""
    return [code for code, _ in getattr(settings, 'LANGUAGES', [])]


_valid_language_codes_set = None


def get_valid_language_codes():
    """지원 언어 코드 집합 (캐시). config 미들웨어·뷰 검증용."""
    global _valid_language_codes_set
    if _valid_language_codes_set is None:
        _valid_language_codes_set = frozenset(get_supported_language_codes())
    return _valid_language_codes_set


def get_request_language(request):
    """요청의 현재 언어 (미들웨어에서 설정). 없으면 'en'."""
    return getattr(request, 'LANGUAGE_CODE', None) or 'en'


def _title_case_word(w: str) -> str:
    """한 단어(또는 슬래시로 구분된 한 덩어리)에 대해 첫 글자 대문자, 나머지 소문자."""
    if not w:
        return w
    return w[0].upper() + (w[1:].lower() if len(w) > 1 else '')


def _normalize_title_case_latin(text: str) -> str:
    """
    라틴 계열(es, vi 등) 번역 표기: 단어별 띄어쓰기·슬래시(/) 구분도 유지하며 단어별 첫 글자 대문자.
    예: healthcare/education → Healthcare/Education, medical / education → Medical / Education.
    CamelCase는 단어 구분용 공백 삽입 후 Title Case 적용.
    """
    if not text or not isinstance(text, str):
        return text
    s = text.strip()
    if not s:
        return s
    # CamelCase(공백 없음)인 경우 대문자 앞에 공백 삽입 (SignIn -> Sign In)
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', s)
    # 공백·슬래시를 구분자로 유지하면서 분리: [구분자, ...] 도 반환
    parts = re.split(r'([/\s]+)', s)
    result = ''.join(
        _title_case_word(p) if p and not re.match(r'^[/\s]+$', p) else (p or '')
        for p in parts
    )
    return result or s


def _normalize_display_latin(text: str) -> str:
    """
    라틴 계열(en, es, vi) 공통 표기 규칙. 영어와 동일.
    - 문장(끝이 . ! ?): 첫 글자만 대문자.
    - 비문장(라벨·버튼 등): 단어별 띄어쓰기·슬래시 유지, 단어별 첫 글자 대문자 (Healthcare/Education 등).
    """
    if not text or not isinstance(text, str):
        return text
    s = text.strip()
    if not s:
        return s
    is_sentence = s.rstrip().endswith(('.', '!', '?'))
    if is_sentence:
        return s[0].upper() + s[1:] if len(s) > 1 else s.upper()
    return _normalize_title_case_latin(s)


def normalize_english_display(text: str) -> str:
    """영어 표기 규칙. 문장/구 모두 첫 단어 첫 글자만 대문자(Sentence case)."""
    return normalize_english_for_translation(text)


def normalize_english_for_translation(text: str) -> str:
    """
    영어 번역 DB 저장용 정규화: 문장/구 모두 첫 단어 첫 글자만 대문자.
    - 문장(. ! ? 뒤)이 여러 개면 각 문장 첫 글자 대문자.
    - 각 문장의 나머지 문자는 소문자 기준으로 정리.
    """
    if not text or not isinstance(text, str):
        return text
    s = text.strip()
    if not s:
        return s
    # 문장 경계(. ! ? 뒤 공백)로 나누어 각 조각을 sentence case로 정규화
    parts = re.split(r'(?<=[.!?])\s+', s)
    result = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        part = part.lower()
        part = part[0].upper() + part[1:] if len(part) > 1 else part.upper()
        result.append(part)
    if result:
        return ' '.join(result)
    s = s.lower()
    return s[0].upper() + s[1:] if len(s) > 1 else s.upper()


def _normalize_display_cjk(text: str) -> str:
    """중국어(간체/번체) 공통: 앞뒤 공백 제거, 연속 공백 하나로."""
    if not text or not isinstance(text, str):
        return text
    s = text.strip()
    if not s:
        return s
    return re.sub(r'\s+', ' ', s)


def _has_hangul(text: str) -> bool:
    """문자열에 한글이 포함되어 있으면 True."""
    if not text:
        return False
    return bool(re.search(r'[\uac00-\ud7a3]', str(text)))


def _has_cjk(text: str) -> bool:
    """문자열에 한자/일본어 등 CJK 문자가 포함되어 있으면 True."""
    if not text:
        return False
    return bool(re.search(r'[\u4e00-\u9fff\u3040-\u30ff]', str(text)))


# 달력 연·월 표시용 월 이름 폴백 (DB 번역 없을 때). 1월=인덱스0
_CALENDAR_MONTH_FALLBACK = {
    'en': ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],
    'es': ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'],
    'vi': ['Tháng 1', 'Tháng 2', 'Tháng 3', 'Tháng 4', 'Tháng 5', 'Tháng 6', 'Tháng 7', 'Tháng 8', 'Tháng 9', 'Tháng 10', 'Tháng 11', 'Tháng 12'],
    'zh-hans': ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'],
    'zh-hant': ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'],
}

# 달력 요일 DB 키. 인덱스 0=일요일, 1=월요일, ..., 6=토요일. get_calendar_weekday_display에서 사용
WEEKDAY_KEYS = ['요일_일', '요일_월', '요일_화', '요일_수', '요일_목', '요일_금', '요일_토']

# 달력 요일 헤더 폴백 (DB에 값 없을 때). 인덱스 0=일요일, 1=월요일, ..., 6=토요일
_CALENDAR_WEEKDAY_FALLBACK = {
    'ko': ['일', '월', '화', '수', '목', '금', '토'],
    'en': ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
    'es': ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'],
    'vi': ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'],
    'zh-hans': ['日', '一', '二', '三', '四', '五', '六'],
    'zh-hant': ['日', '一', '二', '三', '四', '五', '六'],
}


def get_calendar_month_display(month_num: int, language_code: str) -> str:
    """
    달력용 월 이름 반환 (1~12). 설정 언어에 맞게 DB 번역 사용, 잘못된 문자(한글/CJK)면 폴백.
    """
    if not (1 <= month_num <= 12):
        return str(month_num)
    lang = (language_code or '').strip() or 'en'
    if lang == 'ko':
        return f'{month_num}월'
    key = f'{month_num}월'
    out = get_display_text(key, lang)
    # es/en/vi일 때 DB 값이 한자(二月 등)이면 폴백 사용
    if out:
        if _has_hangul(out):
            out = None
        elif lang in ('es', 'en', 'vi') and _has_cjk(out):
            out = None
    if not out:
        fallback = _CALENDAR_MONTH_FALLBACK.get(lang)
        if fallback:
            return fallback[month_num - 1]
        return key
    return out


def get_calendar_month_year_display(year: int, month: int, language_code: str) -> str:
    """
    달력 제목용 "연도 + 월" 문자열. 설정 언어에 맞게 반환.
    예: ko → "2026년 2월", es → "Febrero 2026", en → "February 2026"
    """
    lang = (language_code or '').strip() or 'en'
    if lang == 'ko':
        return f'{year}년 {month}월'
    if lang in ('zh-hans', 'zh-hant'):
        y_suffix = get_display_text('년', lang)
        m_suffix = get_display_text('월', lang)
        return f'{year}{y_suffix} {month}{m_suffix}'
    month_name = get_calendar_month_display(month, lang)
    return f'{month_name} {year}'


def get_calendar_weekday_display(day_index: int, language_code: str) -> str:
    """
    달력 요일 헤더 반환. day_index 0=일요일, 1=월요일, ..., 6=토요일.
    DB 키 요일_일~요일_토에 저장된 번역을 사용하고, 없으면 폴백.
    """
    if not (0 <= day_index <= 6):
        return ''
    lang = (language_code or '').strip() or 'en'
    key = WEEKDAY_KEYS[day_index]
    out = get_display_text(key, lang)
    if out and str(out).strip():
        return str(out).strip()
    fallback = _CALENDAR_WEEKDAY_FALLBACK.get(lang)
    if fallback:
        return fallback[day_index]
    return _CALENDAR_WEEKDAY_FALLBACK['en'][day_index]


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
                    if val is not None and str(val).strip():
                        return val
        return None


def save_translation_from_api(key: str, language_code: str, value: str) -> None:
    """
    번역 API 결과를 StaticTranslation에 저장하고 메모리 캐시에 반영.
    - en: 단어·문장 첫 글자 대문자 (normalize_english_for_translation).
    - es, vi: 문장/비문장 구분 + 단어별 첫 글자 대문자.
    - zh-hans, zh-hant: 앞뒤 공백 제거, 연속 공백 정리.
    """
    if not key or not value:
        return
    from translations.models import LANG_CODE_TO_FIELD
    if language_code not in LANG_CODE_TO_FIELD:
        return
    if language_code == 'en':
        value = normalize_english_for_translation(value)
    elif language_code in ('es', 'vi'):
        value = _normalize_display_latin(value)
    elif language_code in ('zh-hans', 'zh-hant'):
        value = _normalize_display_cjk(value)
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
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            '번역 DB 저장 실패 key=%r lang=%s: %s', key[:80] if key else '', language_code, e
        )


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


# 번역 API 실패 시에만 사용. 헤더 언어와 맞추기 위한 최소 UI 문구 (키 → en/es/zh-hans/zh-hant/vi)
_UI_FALLBACK_WHEN_API_FAILED = {
    '미설정': {'en': 'Not set', 'es': 'Sin configurar', 'zh-hans': '未设置', 'zh-hant': '未設定', 'vi': 'Chưa đặt'},
    '에이전트 계정입니다.': {'en': 'Agent account.', 'es': 'Cuenta de agente.', 'zh-hans': '代理账户。', 'zh-hant': '代理帳戶。', 'vi': 'Tài khoản đại lý.'},
    '님, 환영합니다': {'en': ', welcome', 'es': ', bienvenido/a', 'zh-hans': '，欢迎', 'zh-hant': '，歡迎', 'vi': ', chào mừng'},
    '내 플랜:': {'en': 'My plan:', 'es': 'Mi plan:', 'zh-hans': '我的计划：', 'zh-hant': '我的計劃：', 'vi': 'Kế hoạch của tôi:'},
    '고객 예약 달력': {'en': 'Appointment calendar', 'es': 'Calendario de citas', 'zh-hans': '预约日历', 'zh-hant': '預約日曆', 'vi': 'Lịch hẹn'},
    '메시지 함': {'en': 'Messages', 'es': 'Mensajes', 'zh-hans': '消息', 'zh-hant': '訊息', 'vi': 'Tin nhắn'},
    '컨텐츠 보기': {'en': 'View content', 'es': 'Ver contenido', 'zh-hans': '查看内容', 'zh-hant': '檢視內容', 'vi': 'Xem nội dung'},
    '플랜': {'en': 'Plan', 'es': 'Plan', 'zh-hans': '计划', 'zh-hant': '計劃', 'vi': 'Kế hoạch'},
    '고객이 신청한 약속을 날짜별로 확인하고, 수락하거나 메시지를 보낼 수 있습니다.': {
        'en': 'View and accept customer appointments by date, or send messages.',
        'es': 'Vea y acepte citas por fecha o envíe mensajes.',
        'zh-hans': '按日期查看并接受客户预约，或发送消息。',
        'zh-hant': '按日期查看並接受客戶預約，或發送訊息。',
        'vi': 'Xem và chấp nhận lịch hẹn theo ngày hoặc gửi tin nhắn.',
    },
    '번역에 실패했습니다. 일부 문구가 원문으로 표시될 수 있습니다.': {
        'en': 'Translation failed. Some text may appear in the original language.',
        'es': 'Error de traducción. Parte del texto puede mostrarse en el idioma original.',
        'zh-hans': '翻译失败。部分内容可能显示为原文。',
        'zh-hant': '翻譯失敗。部分內容可能顯示為原文。',
        'vi': 'Dịch thất bại. Một số văn bản có thể hiển thị bằng ngôn ngữ gốc.',
    },
    '번역 실패': {
        'en': 'Translation failed',
        'es': 'Error de traducción',
        'zh-hans': '翻译失败',
        'zh-hant': '翻譯失敗',
        'vi': 'Dịch thất bại',
    },
    '건': {'vi': 'mục'},  # 한글 단위(건) → 베트남어
}


def get_display_text(key_text: str, language_code: str | None = None) -> str:
    """
    헤더 설정 언어로 표시 문구 반환.
    1) 텍스트를 뿌릴 때 헤더의 언어 설정값(language_code) 사용
    2) 번역 DB에서 해당 키/언어 조회
    3) 없으면 번역 API로 DB 갱신 후 1번부터 다시 조회
    4) API 실패 등으로 여전히 한글만 남은 경우, UI용 최소 폴백으로 설정 언어 반환
    """
    if not key_text:
        return ''
    if language_code is None:
        from django.utils import translation
        language_code = (translation.get_language() or 'en').strip()
    else:
        language_code = (language_code or 'en').strip()
    key_clean = (key_text or '').strip()
    if not key_clean:
        return key_text

    def _fetch():
        """1·2: DB/캐시에서 헤더 언어 기준으로 조회. 비한글 요청인데 한글 값이면 미번역으로 간주."""
        v = get_from_cache(key_clean, language_code)
        if v is None or not str(v).strip():
            return None
        if language_code != 'ko' and _has_hangul(str(v)):
            return None
        return str(v).strip()

    value = _fetch()
    if value:
        return value

    # 3: DB에 없거나 미번역 → 번역 API로 DB 갱신 후 1번부터 다시 실행
    if language_code == 'ko':
        ensure_static_translation_key(key_clean, 'ko')
        invalidate_cache()
        value = _fetch()
        return value or key_clean
    try:
        from translations.services import get_or_translate_with_deepl
        get_or_translate_with_deepl(key_clean, language_code)
        value = _fetch()
        if value and (language_code == 'ko' or not _has_hangul(value)):
            return value
        # API가 번역을 반영하지 못한 경우(키 그대로 반환 등): UI 최소 폴백 + 실패 키 기록
        _set_translation_failed(key_clean)
        fallback_by_lang = _UI_FALLBACK_WHEN_API_FAILED.get(key_clean)
        if fallback_by_lang and language_code in fallback_by_lang:
            return fallback_by_lang[language_code]
        return value or key_clean
    except Exception as e:
        _set_translation_failed(key_clean, str(e))
        fallback_by_lang = _UI_FALLBACK_WHEN_API_FAILED.get(key_clean)
        if fallback_by_lang and language_code in fallback_by_lang:
            return fallback_by_lang[language_code]
        return key_clean


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
        language_code = translation.get_language() or 'en'
    for obj in objects:
        for name in field_names:
            raw = getattr(obj, name, None)
            display = get_display_text(str(raw or ''), language_code)
            setattr(obj, f'{name}_display', display)
