# 설문/견적/가격 노출 지점 재점검 (Step 1)

landinghelp_server 기준으로 현재 구현된 **정착플랜/견적/메시징/번역/결제** 흐름과, **설문·견적 입력·가격 노출·이메일** 관련 지점을 정리한 문서입니다.

---

## 1. 고객 설문/견적 입력 화면

### 1.1 견적 입력 화면 — **있음**

| 항목 | 내용 |
|------|------|
| **URL** | `/services/settlement/quote/` (`name='settlement_quote'`) |
| **뷰** | `settlement.views.settlement_quote` |
| **템플릿** | `templates/services/settlement_quote.html` |
| **역할** | 정착 서비스 선택, 이주 정보(State/도시/입국예정일), 서비스 일정(달력 드래그), 추가 문의사항, 제출 시 견적·Checkout 합계 저장 |

입력 항목: 서비스 선택(체크박스), State, 도시, 입국/이주 예정일, 이름, 이메일(히든), 메모, 서비스 일정(JSON). 로그인 시 `UserSettlementPlan`에서 초기값 로드.

### 1.2 설문 전용 화면 — **없음**

별도의 “설문(survey)” 전용 페이지/플로우는 없음. 위 견적 화면이 고객 정보·선호·일정 수집 역할을 함.  
**추가 시 권장**: 설문 전용 단계가 필요하면 `settlement_quote` 이전에 `/services/settlement/survey/` 같은 설문 뷰/폼을 두고, 완료 후 `settlement_quote`로 이동하거나 같은 플로우에 “설문 단계”를 끼워 넣는 방식이 적합함.

---

## 2. 고객 입력 저장 — 모델/엔드포인트

### 2.1 최종 제출 시 저장

| 저장 대상 | 모델 | 엔드포인트 | 비고 |
|-----------|------|------------|------|
| 견적 신청 1건 | `SettlementQuoteRequest` | `POST /services/settlement/quote/` (폼 제출) | `settlement_quote` 뷰에서 `form.is_valid()` 시 생성 |
| 로그인 사용자 플랜 | `UserSettlementPlan` | 동일 (같은 POST에서 `update_or_create`) | 1 user : 1 plan, 스케줄·checkout_total 등 덮어쓰기 |

**관련 파일**

- `settlement/views.py`: `settlement_quote()` — POST 분기에서 `SettlementQuoteRequest` 생성, 로그인 시 `UserSettlementPlan.objects.update_or_create(...)`
- `settlement/forms.py`: `SettlementQuoteForm` — services, state, city, entry_date, name, email, memo
- `settlement/models.py`: `SettlementQuoteRequest`, `UserSettlementPlan`

### 2.2 임시 저장/초안 저장 — **없음**

- **임시 저장(draft)** 전용 API/뷰 없음.
- 스케줄·이주정보는 “제출” 시에만 DB에 반영됨.  
  로그인 사용자는 다음 방문 시 `UserSettlementPlan` 초기값으로 이전 제출 내용이 폼에 채워짐(초안처럼 보이지만, 별도 draft 플래그는 없음).

**추가 시 권장**

- `UserSettlementPlan`에 `is_draft` 필드 추가, 또는
- `SettlementQuoteRequest`에 `status='draft'` 등으로 “초안” 구분 후,  
  **임시 저장 전용 엔드포인트** 1개 추가 (예: `POST /api/settlement/draft/` 또는 `PATCH /api/settlement/plan/`)에서 `UserSettlementPlan`만 갱신하고 리다이렉트 없이 200 반환.

---

## 3. 가격 노출이 발생하는 UI/API 지점

### 3.1 UI (템플릿/컨텍스트)

| 위치 | 노출 내용 | 데이터 소스 |
|------|-----------|-------------|
| `templates/services/settlement_quote.html` | 서비스별 단가, 플로팅 요약 패널 합계, 저장된 Checkout 합계 | `service_prices_json`, `saved_checkout_total`, JS 내 `servicePrices`, `calcCheckoutTotal()` |
| `templates/app/customer_dashboard.html` | 예상 Checkout 합계 | `user_plan.checkout_total`, `user_plan.has_agent_assignment` |
| `templates/home.html` | 예상 Checkout (로그인 고객) | 동일 |
| `templates/billing/subscription_plan.html` | 월 요금 | `plan.features.price_monthly` |
| `templates/billing/subscription_checkout.html` | 월 요금 | 동일 |

### 3.2 API/뷰에서 가격 계산·전달

| 위치 | 역할 |
|------|------|
| `settlement/views.py` — `settlement_quote()` | `calc_checkout_total(schedule, free_agent_service_codes=...)` 호출 → `checkout_total` 계산 후 `SettlementQuoteRequest`/`UserSettlementPlan`에 저장. `service_prices`는 `SettlementService.customer_price`로 구성해 `service_prices_json`으로 템플릿에 전달. `saved_checkout_total`은 기존 플랜의 `checkout_total` (Agent 할당 있을 때만). |
| `settlement/constants.py` — `calc_checkout_total()` | schedule에서 과금 대상 서비스 코드 추출, `SettlementService.customer_price` 합산, 무료 요금제 서비스는 0원 처리. |
| `settlement/views.py` — `api_checkout()` | 결제(모킹) 후 `calc_checkout_total(merged_schedule, ...)`로 합계 계산, `UserSettlementPlan.checkout_total` 갱신. **응답에는 금액 미포함** (`ok`, `message`, `created`만). |

가격이 “노출”되는 API는 **별도 가격 전용 GET API는 없고**,  
- 견적 페이지는 **HTML 렌더 시** `service_prices_json`·`saved_checkout_total`로 노출되고,  
- 고객 대시/홈은 **서버 렌더**로 `user_plan.checkout_total` 노출됩니다.

---

## 4. 이메일 발송 모듈/설정 및 사용처

### 4.1 설정 (config/settings.py)

- `EMAIL_BACKEND`: `os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')` — 기본은 콘솔 백엔드.
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`: 환경변수에서 로드 (설정 가이드에선 .env가 아닌 시스템 환경변수 권장).
- `DEFAULT_FROM_EMAIL`: 발신 주소.

### 4.2 사용처

| 기능 | 파일/함수 | 설명 |
|------|------------|------|
| 아이디 찾기 | `accounts/views.py` — `find_username` | `send_username_reminder(email, usernames, login_url)` 호출 |
| 발송 함수 | `accounts/services.py` — `send_username_reminder()` | `send_mail()` 사용 (제목/본문/수신자) |
| 회원가입 후 이메일 인증 | `accounts/views.py` — `signup` | `send_verification_email(user, request)` 호출 |
| 발송 함수 | `accounts/services.py` — `send_verification_email()` | `send_mail()` 사용 (인증 링크 포함) |
| 비밀번호 재설정 | Django 내장 `PasswordResetView` | `registration/password_reset_email.html` 등으로 메일 발송 (동일 `send_mail` 계열) |
| 설정 경고 | `config/context_processors.py` — `email_config_warning()` | SMTP 백엔드인데 `EMAIL_HOST_USER`/`EMAIL_HOST_PASSWORD` 비어 있으면 `email_config_warning` 플래그로 템플릿에 경고 노출 |

**정착/견적/결제 플로우에서는 이메일 발송 없음** (견적 제출·checkout 완료 시 메일 자동 발송 로직 없음).

---

## 5. 이번 변경에 적합한 삽입 지점 2~3개 제안

아래는 “설문 추가, 임시 저장, 가격 제어, 견적/결제 후 이메일” 같은 변경을 넣기 좋은 위치입니다.

1. **견적/설문 “제출 전” 단계 — 설문 또는 초안 저장**  
   - **위치**: `settlement/views.py` — `settlement_quote()` **GET** 분기 끝 (폼만 렌더하기 직전) 또는 **새 뷰** `settlement_survey`를 만들어 `config/urls.py`에 `/services/settlement/survey/` 등으로 등록.  
   - **이유**: 설문을 “견적 이전 단계”로 두려면 별도 URL/뷰가 명확함. 같은 페이지에서 “저장만 하고 제출 안 함”을 지원하려면 `settlement_quote()` POST에서 `action=save_draft` 같은 파라미터로 분기하거나, 아래 API를 호출하도록 할 수 있음.

2. **임시/초안 저장 API (신규)**  
   - **위치**: `settlement/views.py`에 예) `api_settlement_plan_save(request)` 추가, `config/urls.py`에 `path('api/settlement/plan/', api_settlement_plan_save)` 등으로 등록.  
   - **역할**: POST/PATCH로 `service_schedule`, `state`, `city`, `entry_date` 등만 받아서 **로그인 사용자**의 `UserSettlementPlan`만 `update_or_create` (결제/견적 제출과 분리). 필요 시 `is_draft` 플래그나 `SettlementQuoteRequest.status` 확장.  
   - **이유**: 프론트에서 “저장만” 버튼으로 주기적으로 저장하게 할 수 있고, 가격/노출 정책을 나중에 이 API 직전/직후에 끼우기 좋음.

3. **가격 노출·결제 완료 후 이메일**  
   - **가격 노출 통제**: `settlement/views.py`의 `settlement_quote()`에서 `service_prices`를 만들 때, 그리고 `calc_checkout_total`을 호출하는 모든 지점에서 “역할/요금제/국가” 등에 따라 0원 처리·숨김·다른 금액 적용을 넣기 좋음.  
   - **결제 후 이메일**: `settlement/views.py` — `api_checkout()` **성공 응답 직전**에 “결제 완료/견적 확정” 메일을 보내는 `send_mail()` 또는 `accounts.services`에 `send_checkout_confirmation_email(customer_email, ...)` 같은 함수를 추가해 호출.  
   - **이유**: 가격은 이미 `settlement_quote`·`calc_checkout_total`·`api_checkout`에서만 사용되므로, 여기 2~3곳만 정리하면 됨. 이메일은 “결제 완료” 시점이 명확해 삽입 지점이 한 곳임.

---

## 6. 파일/함수 목록 요약

| 구분 | 파일 | 함수/항목 |
|------|------|-----------|
| 견적 입력 화면 | `settlement/views.py` | `settlement_quote` |
| 견적 폼 | `settlement/forms.py` | `SettlementQuoteForm` |
| 견적/플랜 모델 | `settlement/models.py` | `SettlementQuoteRequest`, `UserSettlementPlan`, `SettlementService` |
| 가격 계산 | `settlement/constants.py` | `calc_checkout_total` |
| 결제(모킹) | `settlement/views.py` | `api_checkout` |
| 가격 노출 UI | `templates/services/settlement_quote.html`, `templates/app/customer_dashboard.html`, `templates/home.html`, `templates/billing/subscription_*.html` | 위 3절 참고 |
| 이메일 설정 | `config/settings.py` | `EMAIL_*`, `DEFAULT_FROM_EMAIL` |
| 이메일 발송 | `accounts/services.py` | `send_username_reminder`, `send_verification_email` |
| 이메일 사용 | `accounts/views.py` | `find_username`, `signup` |
| 이메일 경고 | `config/context_processors.py` | `email_config_warning` |

이 문서는 “설문/견적/가격 노출” 재점검 Step 1 결과물이며, 위 삽입 지점을 기준으로 다음 단계(설문 필드 설계, draft API 스펙, 가격/이메일 정책)를 진행하면 됩니다.
