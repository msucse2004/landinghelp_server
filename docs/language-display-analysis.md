# 헤더 언어(EN) 선택 시에도 한글이 나오는 문제 분석

## 현상
- 헤더에서 "EN English" 선택 후에도 다음이 한글로 표시됨:
  - Plan: **베이직**, 에이전트 계정입니다., my plan: **베이직**, **고객 예약 달력** 버튼

## 원인 후보 (우선순위)

### 1. DB/캐시에 영어 컬럼에 한글이 저장된 경우 (가장 유력)
- `get_display_text(key, 'en')` 동작:
  1. `get_from_cache(key, 'en')` 호출
  2. 캐시에 해당 key의 `en` 값이 **있으면 그대로 반환**
- StaticTranslation에 `key='에이전트 계정입니다.'`, `en='에이전트 계정입니다.'` 처럼 **en 컬럼에 한글이 들어가 있으면** 캐시가 한글을 반환함.
- 코드 폴백(`_CODE_FALLBACK`)은 **캐시/DeepL에서 값을 못 찾았을 때만** 사용되므로, 캐시가 한글을 주면 폴백으로 가지 않음.

### 2. get_from_cache가 빈 문자열을 반환하는 경우
- `_load_cache()`는 `if val:` 일 때만 `cache[k][lang_code] = val` 설정 → 빈 문자열이면 `en` 키가 없음 → `by_lang.get('en')` → None.
- 다만 `getattr(row, field_name, None) or ''` 후 `if val:` 이므로, **공백만 있는 값**이 들어가면 truthy일 수 있음. (일반적이진 않음)

### 3. request.LANGUAGE_CODE가 실제로는 'ko'인 경우
- 미들웨어에서 `request.LANGUAGE_CODE = lang` 설정.
- 컨텍스트 프로세서/뷰는 `get_request_language(request)` → `request.LANGUAGE_CODE or 'en'` 사용.
- LocaleMiddleware가 우리 미들웨어보다 **먼저** 실행되어 세션의 'ko'로 설정했다가, 우리 미들웨어가 덮어쓰므로, 정상이라면 최종값은 우리 미들웨어 기준이어야 함.
- 세션/쿠키와 드롭다운이 불일치(드롭다운만 EN, 세션은 ko)인 경우, **폼 제출(set_language) 없이** 페이지만 새로고침하면 세션 기준으로 동작할 수 있음. (드롭다운은 클라이언트 상태일 뿐)

### 4. 캐시 키 불일치
- 캐시 키는 `StaticTranslation.key`(한글 원문) 기준.
- 뷰/컨텍스트에서 넘기는 키와 DB의 key가 완전히 같아야 함 (공백/마침표 등).

## 조치

1. **방어 로직 추가**: 요청 언어가 `ko`가 아닐 때, 캐시/DB에서 받은 값에 **한글이 포함되어 있으면** "번역 없음"으로 간주하고 코드 폴백 사용.
2. **캐시 빈 문자열 처리**: `get_from_cache`에서 `val`이 빈 문자열/공백만 있으면 None으로 간주해 폴백으로 넘어가도록 통일.
3. **(선택) DB 점검**: StaticTranslation에서 `en`(및 다른 비한글어) 컬럼에 한글이 들어간 행이 있으면 수정하거나, 위 방어 로직으로 표시만 우선 정정.
