# 번역 저장 흐름 & 훅 삽입 지점

## 1. 발견된 파일/함수 목록

### A. DeepL·API 키

| 파일 | 내용 |
|------|------|
| **config/deepl_env.py** | `get_deepl_auth_key()` — `DEEPL_AUTH_KEY`를 env → Windows 레지스트리 → PowerShell 순으로 조회 |
| **config/settings.py** | `DEEPL_AUTH_KEY = get_deepl_auth_key()`, `GOOGLE_TRANSLATE_ENABLED`, `GOOGLE_TRANSLATE_API_KEY` |
| **settlement/management/commands/translate_po.py** | `DEEPL_AUTH_KEY` 직접 참조, 자체 `translate_text(translator, ...)` (DeepL 호출) |

### B. 번역 서비스 (실제 DeepL/Google 호출)

| 파일 | 함수 | 역할 |
|------|------|------|
| **translations/services.py** | `_get_deepl_translator()` | DeepL API 키 로드 후 `deepl.Translator` 반환 |
| **translations/services.py** | `_translate_with_google(...)` | Google Cloud Translation v2 호출 |
| **translations/services.py** | `_translate_one_deepl(translator, text, target_deepl, source_deepl)` | DeepL 1문장 번역 (429 시 1회 재시도) |
| **translations/services.py** | **`_translate_one(text, target_lang, source_lang)`** | **Google → DeepL 순으로 1문장 번역, 결과만 반환(저장 안 함)** |
| **translations/services.py** | **`get_or_translate_with_deepl(key, target_lang)`** | 캐시 조회 → 없으면 `_translate_one` → **`save_translation_from_api`로 DB 저장** |
| **translations/services.py** | **`translate_and_save_to_static(key_text, source_lang)`** | 키 등록 후 언어별 `_translate_one` → **`save_translation_from_api`** |

### C. DB/캐시 저장

| 파일 | 함수 | 역할 |
|------|------|------|
| **translations/utils.py** | **`save_translation_from_api(key, language_code, value)`** | **StaticTranslation에 value 저장 + 캐시 갱신. en이면 normalize_english_display 적용** |
| **translations/models.py** | `StaticTranslation` | 고정 번역 모델 (key, ko, en, es, zh_hans, zh_hant, vi) |

### D. 번역 “소비” (조회 시 없으면 번역·저장 유도)

| 파일 | 함수/위치 | 호출 관계 |
|------|-----------|-----------|
| **translations/utils.py** | **`get_display_text(key_text, language_code)`** | DB/캐시 없으면 **`get_or_translate_with_deepl(key_clean, language_code)`** → 그 안에서 `_translate_one` + **`save_translation_from_api`** |
| **translations/apps.py** | `ready()` 내 gettext 래핑 | `translation.gettext` 오버라이드 → **`get_or_translate_with_deepl(key, lang)`** 호출 |
| **config/context_processors.py** | `_settlement_i18n`, `translation_failed_alert` | **`get_display_text(msg_key, lang)`** 다수 호출 |
| **billing/context_processors.py** | 플랜 라벨 등 | **`get_display_text(...)`** |
| **settlement/views.py** | `settlement_quote` | **`get_display_text(...)`** 로 settlement_i18n dict 구성 |
| **content/signals.py** | `_translate_text_field` | 캐러셀/콘텐츠 저장 시 **`translate_and_save_to_static(value, source_lang)`** |

### E. 관리 명령·po (번역 후 DB/파일 저장)

| 파일 | 호출 관계 |
|------|-----------|
| **translations/management/commands/fill_translations_deepl.py** | `_translate_one(source_text, lang, 'ko')` → **`save_translation_from_api(row.key, lang, translated_text)`** |
| **translations/management/commands/fill_translations_and_list_failed.py** | 동일: `_translate_one` → **`save_translation_from_api`** |
| **settlement/management/commands/translate_po.py** | 자체 `translate_text(translator, ...)` (DeepL) → **`save_translation_from_api(entry.msgid, target_lang, translated)`** (그리고 po entry.msgstr에도 기록) |

### F. 메시지 화면 번역 (Message·MessageTranslation)

| 파일 | 함수 | 역할 |
|------|------|------|
| **messaging/views.py** | **`_detect_and_translate_to_en(body_text)`** | langdetect → **`_translate_one(body_text, 'en', detected)`** → `Message.body_en`용 문자열 반환 (DB 저장은 호출자) |
| **messaging/views.py** | **`_get_message_body_for_viewer(msg, user)`** | 선호어 번역 없으면 **`_translate_one(body, pref, source)`** → **`MessageTranslation.update_or_create(...)`** 로 캐시 저장 |
| **messaging/signals.py** | `post_save` (Message) | **`_detect_and_translate_to_en(body)`** → `msg.detected_lang`, `msg.body_en` 할당 후 저장 |
| **messaging/views.py** | `api_send_message` | 전송 시 **`_detect_and_translate_to_en(body)`** 로 `msg.body_en` 설정 |

---

## 2. 호출 관계 요약

```
[화면/템플릿]
    → get_display_text(key, lang)
        → get_or_translate_with_deepl(key, lang)
            → _translate_one(key, lang, source)   ← DeepL(또는 Google) 호출
            → save_translation_from_api(key, lang, translated)   ← DB 저장

[관리자 콘텐츠 저장]
    → translate_and_save_to_static(key_text, source_lang)
        → _translate_one(key_text, lang, source_lang)
        → save_translation_from_api(...)

[fill_translations_* 커맨드]
    → _translate_one(source_text, lang, 'ko')
    → save_translation_from_api(row.key, lang, translated_text)

[translate_po 커맨드]
    → translate_text(translator, ...)  # 자체 DeepL 호출
    → save_translation_from_api(entry.msgid, target_lang, translated)

[메시지 저장/표시]
    → _detect_and_translate_to_en(body)  → _translate_one(..., 'en', detected)  → Message.body_en / MessageTranslation
    → _get_message_body_for_viewer      → _translate_one(body, pref, source)   → MessageTranslation.update_or_create
```

---

## 3. 훅(hook) 삽입 지점 제안

### 훅 1 (권장): “번역 결과를 DB에 넣기 직전” — `save_translation_from_api` 직전

- **위치**: **`translations/services.py`**
- **방법**:  
  - `_translate_one`의 반환값을 그대로 쓰지 않고, **“저장용 최종 문장”을 만드는 함수**를 둠.  
    예: `def apply_post_edit(text: str, key: str, target_lang: str, source_lang: str) -> str`  
    - 내부: placeholder 보호 후 Ollama 후편집.  
    - 실패 시 입력 `text` 그대로 반환(DeepL 결과 유지).
  - **`get_or_translate_with_deepl`**  
    `translated = _translate_one(...)` 다음에  
    `translated = apply_post_edit(translated, canonical_key, target_lang, source_lang)`  
    넣고, 그 결과를 **`save_translation_from_api(canonical_key, target_lang, translated)`**에 넘김.
  - **`translate_and_save_to_static`**  
    `translated = _translate_one(...)` 다음에 동일하게 `apply_post_edit` 적용 후 **`save_translation_from_api`**에 넘김.
  - **fill_translations_deepl / fill_translations_and_list_failed**  
    `translated_text = _translate_one(...)` 다음에 `apply_post_edit(..., row.key, lang, 'ko')` 적용 후 **`save_translation_from_api`**에 넘김.
  - **translate_po**  
    `translated = translate_text(...)` 다음에 `apply_post_edit(translated, entry.msgid, target_lang, source)` 적용 후 **`save_translation_from_api`** 및 po 저장.

- **장점**:  
  - StaticTranslation으로 들어가는 모든 경로를 한 번에 “DeepL → Ollama 후편집 → DB”로 통일.  
  - placeholder/포맷 보호·폴백을 `apply_post_edit` 한 곳에서만 구현하면 됨.

---

### 훅 2: “번역 결과를 반환하기 직전” — `_translate_one` 래핑

- **위치**: **`translations/services.py`**
- **방법**:  
  - 새 함수 **`translate_one_pipeline(text, target_lang, source_lang, key=None)`** 정의.  
    - 내부: `raw = _translate_one(text, target_lang, source_lang)`.  
    - raw가 있으면 placeholder 보호 + Ollama 후편집 후 반환; 실패 시 raw 반환.  
    - key는 후편집/로깅용으로 선택 전달.
  - **StaticTranslation 경로**:  
    `get_or_translate_with_deepl`, `translate_and_save_to_static`, fill_translations_* 에서  
    `_translate_one` 대신 **`translate_one_pipeline`** 호출하고, 그 반환값을 **`save_translation_from_api`**에 넘김.
  - **메시지 경로**도 동일 파이프라인을 타게 하려면:  
    `messaging/views.py`의 `_detect_and_translate_to_en`, `_get_message_body_for_viewer`에서  
    `_translate_one` 대신 **`translate_one_pipeline`** 호출.  
    (메시지는 StaticTranslation이 아니라 Message/MessageTranslation에 저장)

- **장점**:  
  - “번역 결과를 반환하는 곳”이 한 군데로 모임.  
  - UI 문구(StaticTranslation)와 메시지 본문(Message/MessageTranslation) 모두 동일한 후편집 정책 적용 가능.

---

## 4. 요약 표

| 구분 | 훅 1 (save 직전) | 훅 2 (translate 반환 직전) |
|------|------------------|-----------------------------|
| 삽입 위치 | `save_translation_from_api`를 호출하는 모든 곳에서, 넘기기 직전에 `apply_post_edit` | `_translate_one` 대신 `translate_one_pipeline` 호출 |
| 수정 파일 수 | services.py, translate_po, fill_translations_* (4곳) | services.py + 위 동일 + messaging/views.py (메시지 포함 시) |
| 메시지 화면 | 별도 처리 필요 (같은 훅 쓰려면 messaging에서 pipeline 호출) | 같은 pipeline으로 통일 가능 |
| placeholder 보호 | `apply_post_edit` 내부에서 일괄 처리 | `translate_one_pipeline` 내부에서 일괄 처리 |

**권장**: 우선 **훅 1**으로 StaticTranslation 저장 직전만 Ollama 후편집을 끼워 넣고,  
필요하면 메시지용은 `_translate_one` 대신 **`translate_one_pipeline`**을 쓰도록 **훅 2**를 추가하는 방식이 구현·검증이 단순합니다.
