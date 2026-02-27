# 번역 지원 검증 요약

## 지원 언어 (6개)

| 코드 | 표시명 | StaticTranslation 컬럼 | Django locale |
|------|--------|------------------------|---------------|
| ko | KR 한국어 | ko | locale/ko/ |
| en | EN English | en | locale/en/ |
| es | ES Español | es | locale/es/ |
| zh-hans | ZH 中文(简体) | zh_hans | locale/zh_Hans/ |
| zh-hant | ZH 中文(繁體) | zh_hant | locale/zh_Hant/ |
| vi | VI Tiếng Việt | vi | locale/vi/ |

설정: `config/settings.py` → `LANGUAGES`, `LOCALE_PATHS`

---

## 번역 소스 (2가지)

### 1. StaticTranslation (DB + CSV)

- **역할**: 고정 문구(버튼, 라벨, 달력 월명 등)의 다국어 저장
- **위치**: `translations.models.StaticTranslation`, `static_translations_all.csv`
- **사용처**: `get_display_text(key, language_code)` → 뷰/콘텍스트 프로세서에서 사용
- **지원 언어**: ko, en, es, zh_hans, zh_hant, vi 6개 컬럼 모두 사용
- **캐시**: `translations.utils` 메모리 캐시, `import_static_translations_csv` 실행 시 `invalidate_cache()` 호출

**확인된 사용처**

- 정착 서비스: `config.context_processors.settlement_nav_i18n` (서브네비, 메인, 소개, 후기, 비용예상)
- 정착 플랜 페이지: `settlement.views.settlement_quote` → `settlement_i18n`, `services_by_category`, `tier_info.description`, `free_agent_services` 라벨
- 고객 대시보드: `config.views.customer_dashboard` → `dashboard_calendar_i18n` (달력 제목)
- 홈: `config.views.home` → `plan_calendar_i18n` (달력 제목)
- 에이전트 예약 달력: `config.views.agent_appointment_calendar` → `cal_title`

### 2. Django gettext (django.po)

- **역할**: `{% trans "문구" %}` 태그용
- **위치**: `locale/<lang>/LC_MESSAGES/django.po`
- **지원 locale**: ko, en, es, zh_Hans, zh_Hant, vi 6개 디렉터리 존재
- **주의**: `.po` 수정 후 `python manage.py compilemessages` 필요 (gettext 도구 필요)

---

## API

- **`GET /api/i18n/<lang>/`**  
  - `config.views.api_i18n`  
  - `_valid_language_codes()`로 6개 언어만 허용  
  - `LANG_CODE_TO_FIELD`로 해당 언어 컬럼만 조회 후 JSON 반환  
  - **모든 지원 언어 동일하게 동작**

---

## 달력 월/년 표시 (6개 언어 공통)

- **한국어(ko)**: `"2026년 2월"`, 연/월 드롭다운 `"2026년"`, `"2월"`
- **그 외(en, es, zh-hans, zh-hant, vi)**: `"Feb. 2026"` 형식 (월명은 StaticTranslation `1월`~`12월` 해당 언어 컬럼 사용), 연도 드롭다운은 숫자만, 월 드롭다운은 `month_1`~`month_12` 번역값

적용 템플릿/뷰:

- `templates/services/settlement_quote.html` (제목 + 연/월 드롭다운)
- `templates/app/customer_dashboard.html` (제목)
- `templates/home.html` (제목)
- `config.views.agent_appointment_calendar` (제목)

---

## 점검 시 확인할 것

1. **DB/CSV 동기화**  
   - `python manage.py seed_translation_keys`  
   - `python manage.py import_static_translations_csv`  
   - (또는 Admin → 고정 번역 → 「키 동기화 및 CSV 반영」)

2. **빈 번역**  
   - 새로 추가한 문구는 CSV에 해당 키 행이 있어야 함.  
   - 키만 있고 en/es/zh_hans/zh_hant/vi가 비어 있으면 해당 언어에서는 원문(한국어)이 그대로 나올 수 있음.

3. **django.po**  
   - `{% trans %}`만 쓰는 페이지는 `compilemessages` 후 해당 locale이 활성화되어야 번역 적용.

4. **언어 코드 일치**  
   - 요청 언어: `request.LANGUAGE_CODE` (LocaleMiddleware)  
   - 뷰에서 `get_display_text(..., lang)`에 동일한 코드 전달 (ko, en, es, zh-hans, zh-hant, vi)

---

## 수정 이력 (이번 검증에서 반영한 내용)

- 달력 제목/드롭다운: 영어만이 아니라 **한국어를 제외한 5개 언어** 모두 `"월명. 연도"` 및 월 드롭다운 번역값 사용하도록 변경.
- CSV: `년` en 컬럼을 `年` → `year`, `월` en 컬럼을 `Mon` → `month`로 수정.
