"""
번역 파이프라인: DeepL 1차 번역 → Ollama 후편집(의미 유지 + UI 톤).
placeholder(%(count)s, {name}, {{ name }}, HTML 등) 보호/복원.
보호 용어(PROTECTED_TERMS): 원문에 포함된 구절을 __PT_N__으로 치환 후 번역하고,
  결과에서 __PT_N__을 해당 언어의 고정 번역으로 복원해 단어가 임의로 바뀌지 않게 함.
  새로 고정하고 싶은 단어/구절은 PROTECTED_TERMS에 (원문, {lang: 고정값}) 형태로 추가.

환경변수:
  DEEPL_AUTH_KEY  - DeepL API 키 (필수, DeepL 사용 시)
  OLLAMA_URL      - 기본값 http://localhost:11434
  OLLAMA_MODEL    - 기본값 llama3.1:8b

Shell 테스트 예시 (단위 테스트 없이 확인):
  python manage.py shell
  >>> from translations.translation_pipeline import translate_deepl, post_edit_ollama, translate_pipeline
  >>> translate_deepl('저장되었습니다.', 'en', 'ko')
  'It has been saved.'
  >>> post_edit_ollama('저장되었습니다.', 'It has been saved.', 'en')
  'Saved.'   # Ollama 서버 기동 시
  >>> translate_pipeline('저장되었습니다.', 'en')
  'Saved.'   # DeepL → Ollama, Ollama 실패 시 DeepL 결과 반환
  >>> translate_pipeline('%(count)s개의 메시지가 있습니다.', 'en')
  'You have %(count)s messages.'  # placeholder 유지
"""
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

# 환경변수 (키는 코드/깃에 넣지 않음)
def _get_deepl_auth_key() -> str:
    try:
        from config.deepl_env import get_deepl_auth_key as _get
        return (_get() or '').strip()
    except Exception:
        return (os.environ.get('DEEPL_AUTH_KEY') or '').strip()


def _ollama_base_url() -> str:
    """OLLAMA_URL 기본값: http://localhost:11434 (api/chat은 요청 시 추가)."""
    return (os.environ.get('OLLAMA_URL') or 'http://localhost:11434').strip().rstrip('/')


def _ollama_model() -> str:
    return (os.environ.get('OLLAMA_MODEL') or 'llama3.1:8b').strip()


# 우리 언어 코드 → DeepL target (pipeline 전용, services와 동일)
LANG_TO_DEEPL = {
    'ko': 'KO',
    'en': 'EN-US',
    'zh-hans': 'ZH-HANS',
    'zh-hant': 'ZH-HANT',
    'vi': 'VI',
    'es': 'ES',
}

# 보호 용어: 원문에 포함되면 치환 토큰(__PT_0__ 등)으로 보냄 → 번역 후 목표 언어 고정값으로 복원.
# 파이프라인이 "정착"→relocation 등으로 바꾸지 않도록 함. 긴 구절을 먼저 넣을 것.
PROTECTED_TERMS = [
    # (원문 구절, { target_lang: 번역 고정값 })
    ("정착 플랜", {"en": "settlement plan", "es": "plan de asentamiento", "zh-hans": "安家计划", "zh-hant": "安家計劃", "vi": "kế hoạch định cư"}),
    ("정착 서비스", {"en": "settlement service", "es": "servicio de asentamiento", "zh-hans": "安家服务", "zh-hant": "安家服務", "vi": "dịch vụ định cư"}),
    ("정착", {"en": "settlement", "es": "asentamiento", "zh-hans": "安家", "zh-hant": "安家", "vi": "định cư"}),
]

# placeholder 패턴 (복원 순서 유지를 위해 리스트로 순서대로 매칭)
_PLACEHOLDER_PATTERNS = [
    (re.compile(r'%\([^)]+\)[sd]?'), 'PY_FMT'),   # %(count)s, %(name)s
    (re.compile(r'%[sd]'), 'PY_SINGLE'),          # %s, %d (짧은 것 나중에)
    (re.compile(r'\{\{[^}]+\}\}'), 'DBL_BRACE'),  # {{ name }}
    (re.compile(r'\{[^{}\s]+\}'), 'BRACE'),       # {name}, {0}
    (re.compile(r'<[^>]+>'), 'HTML'),             # <a href="...">, </a>
]


def _extract_protected_terms(text: str, target_lang: str) -> tuple[str, list[tuple[str, str]]]:
    """
    원문에서 보호 용어를 __PT_0__, __PT_1__ ... 로 치환하고,
    (placeholder, target_lang에서 쓸 고정 번역) 목록을 반환. 복원 시 __PT_i__ → 고정 번역.
    """
    if not text or not target_lang:
        return text or '', []
    # 긴 구절 우선 매칭 (정착 플랜 → 정착 보다 먼저)
    sorted_terms = sorted(PROTECTED_TERMS, key=lambda x: -len(x[0]))
    replacements: list[tuple[int, int, str, str]] = []  # (start, end, phrase, value)
    i = 0
    while i < len(text):
        matched = False
        for phrase, lang_map in sorted_terms:
            val = (lang_map or {}).get(target_lang)
            if not val:
                continue
            if text[i:i + len(phrase)] == phrase:
                replacements.append((i, i + len(phrase), phrase, val))
                i += len(phrase)
                matched = True
                break
        if not matched:
            i += 1
    # 뒤에서부터 치환 (인덱스 밀림 방지). __PT_0__ = 첫 번째 매칭의 고정값.
    out = text
    result_pairs: list[tuple[str, str]] = [(f'__PT_{i}__', replacements[i][3]) for i in range(len(replacements))]
    for i in reversed(range(len(replacements))):
        start, end = replacements[i][0], replacements[i][1]
        out = out[:start] + f'__PT_{i}__' + out[end:]
    return out, result_pairs


def _restore_protected_terms(text: str, pairs: list[tuple[str, str]]) -> str:
    """__PT_0__, __PT_1__ ... 를 보호 용어의 고정 번역으로 복원."""
    if not text or not pairs:
        return text
    for placeholder, value in pairs:
        text = text.replace(placeholder, value)
    return text


def _extract_placeholders(text: str) -> tuple[str, list[str]]:
    """
    text에서 placeholder를 __PLH_0__, __PLH_1__ ... 로 치환하고,
    원본 placeholder 목록을 반환. (복원 시 동일 순서로 되돌림)
    """
    if not text:
        return '', []
    matches: list[tuple[int, int, str]] = []  # (start, end, original)
    for pattern, _ in _PLACEHOLDER_PATTERNS:
        for m in pattern.finditer(text):
            matches.append((m.start(), m.end(), m.group(0)))
    matches.sort(key=lambda x: x[0])
    placeholders = [m[2] for m in matches]
    # 뒤에서부터 치환해 인덱스 밀림 방지
    out = text
    for i in reversed(range(len(matches))):
        start, end, _ = matches[i]
        out = out[:start] + f'__PLH_{i}__' + out[end:]
    return out, placeholders


def _restore_placeholders(text: str, placeholders: list[str]) -> str:
    """__PLH_0__, __PLH_1__ ... 를 원본 placeholder로 복원."""
    if not text or not placeholders:
        return text
    for i, ph in enumerate(placeholders):
        text = text.replace(f'__PLH_{i}__', ph)
    return text


def translate_deepl(text: str, target_lang: str, source_lang: str = 'ko') -> str:
    """
    DeepL로 1차 번역. placeholder는 보호하지 않음(호출 전에 치환된 텍스트 권장).
    target_lang/source_lang: ko, en, es, zh-hans, zh-hant, vi
    실패 시 빈 문자열. 429 시 1회 재시도.
    """
    text = (text or '').strip()
    if not text:
        return ''
    auth_key = _get_deepl_auth_key()
    if not auth_key:
        logger.warning('translation_pipeline: DEEPL_AUTH_KEY 없음, DeepL 스킵')
        return ''
    target_deepl = LANG_TO_DEEPL.get(target_lang)
    source_deepl = LANG_TO_DEEPL.get(source_lang, 'KO')
    if not target_deepl:
        logger.warning('translation_pipeline: 지원하지 않는 target_lang=%s', target_lang)
        return ''
    try:
        import deepl
        translator = deepl.Translator(auth_key)
    except Exception as e:
        logger.warning('translation_pipeline: DeepL 초기화 실패: %s', e)
        return ''
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
            err_msg = str(e).lower()
            if attempt == 0 and ('429' in err_msg or 'too many' in err_msg or 'rate' in err_msg):
                time.sleep(1.0)
                continue
            logger.warning('translation_pipeline: DeepL 번역 실패 (%s -> %s): %s', source_deepl, target_deepl, e)
            return ''
    return ''


def post_edit_ollama(source_ko: str, draft: str, target_lang: str) -> str:
    """
    Ollama로 후편집: 의미 유지 + UI 톤(짧고 직관). draft를 자연스럽게 다듬어 번역 문장만 반환.
    source_ko: 원문(한국어). draft: DeepL 초안. target_lang: 목표 언어 코드.
    실패/타임아웃 시 빈 문자열(호출자가 DeepL 결과 사용).
    """
    draft = (draft or '').strip()
    if not draft:
        return ''
    base = _ollama_base_url()
    url = base + '/api/chat' if '/api/' not in base else base
    model = _ollama_model()
    lang_names = {'en': 'English', 'es': 'Spanish', 'zh-hans': 'Simplified Chinese', 'zh-hant': 'Traditional Chinese', 'vi': 'Vietnamese', 'ko': 'Korean'}
    lang_name = lang_names.get(target_lang, target_lang)
    system = (
        'You are a post-editor for UI translations. Your task: given a source sentence and a machine-translated draft, '
        'output ONLY the improved translation in the target language—short, clear, and natural for UI. '
        'Do not change or remove placeholders like %(count)s, {name}, {{ name }}, or HTML tags; keep them exactly as in the draft. '
        'Do not translate or alter tokens like __PT_0__, __PT_1__, etc.; keep them exactly as in the draft (they will be replaced later). '
        'Output nothing but the final translation, no explanation.'
    )
    user = f'Source (Korean): {source_ko}\nDraft translation ({lang_name}): {draft}\nOutput only the improved translation:'
    body = json.dumps({
        'model': model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
        'stream': False,
    }).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=body,
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST',
    )
    timeout = 60
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        content = (data or {}).get('message', {}).get('content') or ''
        return (content or '').strip()
    except urllib.error.HTTPError as e:
        logger.warning('translation_pipeline: Ollama HTTPError %s: %s', e.code, e.read()[:200] if e.fp else '')
        return ''
    except urllib.error.URLError as e:
        logger.warning('translation_pipeline: Ollama URLError (서버 미기동?): %s', e.reason)
        return ''
    except (OSError, json.JSONDecodeError, KeyError) as e:
        logger.warning('translation_pipeline: Ollama 요청/파싱 실패: %s', e)
        return ''


def translate_pipeline(source_ko: str, target_lang: str, source_lang: str = 'ko') -> str:
    """
    DeepL → Ollama 후편집 파이프라인. placeholder·보호 용어(PROTECTED_TERMS) 보호/복원 포함.
    폴백: Ollama 실패 → DeepL 결과 반환. DeepL 실패 → 빈 문자열(호출자가 원문 등 처리).
    """
    source_ko = (source_ko or '').strip()
    if not source_ko:
        return ''
    text_for_api, placeholders = _extract_placeholders(source_ko)
    if not text_for_api.strip():
        return source_ko

    # 보호 용어 치환: 정착 → __PT_0__ 등 → 번역 후 목표어 고정값으로 복원
    text_protected, protected_pairs = _extract_protected_terms(text_for_api, target_lang)

    deepl_out = translate_deepl(text_protected, target_lang, source_lang)
    if not deepl_out:
        return ''

    draft_restored = _restore_placeholders(deepl_out, placeholders)
    ollama_out = post_edit_ollama(source_ko, draft_restored, target_lang)
    out = ollama_out if ollama_out else draft_restored
    out = _restore_placeholders(out, placeholders)
    out = _restore_protected_terms(out, protected_pairs)
    return out
