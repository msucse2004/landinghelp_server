# Step 4 — DB 저장 직전 파이프라인 삽입 (변경 요약)

## 수정한 파일과 변경점

### 1. `translations/services.py`

**추가**
- **`_translate_for_save(text, target_lang, source_lang)`**
  - DB 저장용 번역 전용 함수.
  - 먼저 `translate_pipeline`(DeepL→Ollama) 호출.
  - 결과가 있으면 그대로 반환.
  - 예외 또는 빈 결과 시 `_translate_one`(Google→DeepL) 폴백.
  - 둘 다 실패 시 빈 문자열 반환(호출자가 원문 유지 등 처리).

**변경**
- **`get_or_translate_with_deepl`**
  - 기존: `_translate_one` → `save_translation_from_api`.
  - 변경: `_translate_for_save` → 결과 있으면 `save_translation_from_api`, 없으면 **저장 없이** 원문 반환 + `logger.warning` (캐시는 그대로, 재번역만 실패).
  - docstring: “캐시 있으면 재번역 안 함 / Ollama 실패 시 DeepL 결과 저장 / DeepL 실패 시 원문 반환” 명시.

- **`translate_and_save_to_static`**
  - 기존: 언어별 `_translate_one` → 저장 또는 원문 저장.
  - 변경: 언어별 `_translate_for_save` → 결과 있으면 해당 번역 저장, 없으면 원문 저장 + `logger.warning`.

---

### 2. `translations/management/commands/fill_translations_deepl.py`

- **import**: `_translate_one` → `_translate_for_save`.
- **호출**: `_translate_one(source_text, lang, 'ko')` → `_translate_for_save(source_text, lang, 'ko')`.
- 동작: 빈 번역 채우기 시 DeepL→Ollama 파이프라인 사용, 실패 시 기존처럼 DeepL만 사용.

---

### 3. `translations/management/commands/fill_translations_and_list_failed.py`

- **import**: `_translate_one` → `_translate_for_save`.
- **호출**: `_translate_one(source_text, lang, 'ko')` → `_translate_for_save(source_text, lang, 'ko')`.
- 동작: fill 시 파이프라인 사용, 실패 시 폴백 후에도 실패한 키는 기존처럼 리스트에 포함.

---

### 4. `settlement/management/commands/translate_po.py`

- **import**: `get_from_cache`, `save_translation_from_api`에 더해 `get_or_translate_with_deepl` 추가.
- **단수 msgstr**  
  - 기존: `get_from_cache` → 없으면 `translate_text(translator, ...)` → `save_translation_from_api`.
  - 변경: `get_or_translate_with_deepl(entry.msgid, target_lang)` 호출 (캐시 조회 + 파이프라인 + DB 저장은 내부에서 처리).  
  - `save_translation_from_api` 호출 제거(중복 저장 방지).
- **복수 msgstr_plural**  
  - 동일하게 `get_or_translate_with_deepl(to_translate, target_lang)` 사용, 별도 `save_translation_from_api` 제거.

---

## 동작 규칙 정리

| 상황 | 동작 |
|------|------|
| 캐시/DB에 이미 번역 있음 | 재번역하지 않고 그대로 사용(캐시 역할). |
| DeepL → Ollama 성공 | 파이프라인 결과를 최종 저장. |
| Ollama 실패 | DeepL 결과만 저장 (`translate_pipeline` 내부 폴백). |
| DeepL(및 폴백) 실패 | 원문 또는 기존 번역 유지, 저장 없음 + 경고 로그. |
| 화면 표시 | 번역 실패 시에도 원문/폴백 반환만 하고 예외로 화면을 깨지 않음(기존 `get_display_text` 동작 유지). |

---

## Diff 요약 (핵심만)

```
translations/services.py
  + _translate_for_save()  (파이프라인 → _translate_one 폴백)
  - get_or_translate_with_deepl: _translate_one → _translate_for_save, 실패 시 로그 후 원문 반환
  - translate_and_save_to_static: _translate_one → _translate_for_save, 실패 시 원문 저장 + 로그

translations/management/commands/fill_translations_deepl.py
  - _translate_one → _translate_for_save

translations/management/commands/fill_translations_and_list_failed.py
  - _translate_one → _translate_for_save

settlement/management/commands/translate_po.py
  + get_or_translate_with_deepl import
  - StaticTranslation 경로: get_from_cache + translate_text + save → get_or_translate_with_deepl (저장 내부 처리)
  - save_translation_from_api 호출 제거(해당 경로)
```
