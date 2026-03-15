# 통합 정리 요약 (Survey → Admin Review → Quote → Payment → Scheduling → Calendar → AI → Reviews)

마지막 통합 검토 결과 요약.

---

## 1. Changed files (이번 정리에서 수정/추가된 파일)

| 파일 | 변경 내용 |
|------|-----------|
| `docs/WORKFLOW_AND_INTEGRATION.md` | **신규** — 워크플로우 상태 전이, 스케줄링 엔진, PDF/이메일 송부, 향후 연동 포인트 문서 |
| `docs/INTEGRATION_REVIEW_SUMMARY.md` | **신규** — 본 요약 문서 |
| `settlement/tests/__init__.py` | **신규** — settlement 테스트 패키지 |
| `settlement/tests/test_workflow_critical.py` | **신규** — 가격 노출 정책 단위 테스트 (10개) |
| `README.md` | Developer documentation 링크 및 critical workflow 테스트 실행 안내 추가 |

---

## 2. Migrations added (이번 정리에서 추가된 마이그레이션)

**없음.** 이번 통합 작업에서는 새 마이그레이션을 추가하지 않았습니다.  
기존 플로우에서 이미 사용 중인 마이그레이션은 그대로 유지됩니다 (예: `settlement/migrations/0020_schedule_domain_models.py`, `accounts/migrations/0018_agentrating_appointment_partial_unique.py` 등).

---

## 3. 검토 결과 요약

### 3.1 중복 로직 (Duplicated logic)

- **공유 대화 생성:** `settlement/notifications.py`의 `_get_or_create_shared_conversation(submission)` 한 곳에서만 사용. 중복 없음.
- **견적 송부:** `finalize_and_send_quote()` 한 진입점(Admin 저장 액션 + config 검토 페이지). 이메일/알림 중복 발송 없음.
- **가격 노출 여부:** `message_may_include_price()`, `can_view_price()`, `quote.customer_can_see_prices()`, `quote_for_customer()`로 일관되게 적용. 쿼리에서 `status__in=(FINAL_SENT, PAID)` 반복은 있으나, 정책은 constants + 모델에 집중되어 있음.

### 3.2 상태 전이 일관성 (Status transitions)

- **SurveySubmission:** DRAFT → SUBMITTED → (REVISION_REQUESTED → SUBMITTED) → AWAITING_PAYMENT → AGENT_ASSIGNMENT → SERVICE_IN_PROGRESS. 전이는 `survey/views.py`, `config/views.py`, `settlement/quote_approval.py`, `settlement/quote_checkout.py`, `settlement/views.py`에서만 수행되며 문서화됨.
- **SettlementQuote:** DRAFT/NEGOTIATING → FINAL_SENT → PAID. FINAL_SENT 전이는 `finalize_and_send_quote()`, PAID 전이는 `api_quote_checkout` 결제 완료 시만.
- **ServiceSchedulePlan:** DRAFT → REVIEWING → FINALIZED → SENT. `config/schedule_admin_views.submission_review_schedule_finalize`에서만 SENT로 전이.
- **AgentAppointmentRequest:** PENDING → CONFIRMED / CANCELLED. 기존 뷰/시그널과 일치.

### 3.3 알림 중복 방지 (Notifications)

- 설문 제출: `survey/views.py` 제출 처리에서 1회만 호출 (admin 알림, 고객 이메일/메시지, admin 메시지).
- 견적 송부: `finalize_and_send_quote()` 1회 호출로 이메일 + 앱 메시지.
- 결제 완료: `api_quote_checkout`에서 `send_payment_complete_notifications()` 1회.
- 일정 송부: `submission_review_schedule_finalize`에서 `send_schedule_sent_to_customer()` 1회.

### 3.4 고객 가격 노출 (Price exposure)

- `status < FINAL_SENT`일 때 고객에게 가격/합계/결제 링크 노출 금지.  
- 적용 위치: `settlement/constants.py` (`message_may_include_price`, `can_view_price`, `quote_for_customer`), `settlement/views.py` (고객 견적/결제), `settlement/quote_email.py`, `settlement/notifications.py`, Admin 읽기 전용 견적.  
- 테스트: `settlement.tests.test_workflow_critical.PriceVisibilityTests`에서 검증.

### 3.5 하위 호환성 (UserSettlementPlan.service_schedule)

- `schedule_utils.get_schedule_for_display(user_or_plan)`이 ACTIVE/SENT `ServiceSchedulePlan` 우선, 없으면 기존 `UserSettlementPlan.service_schedule` JSON 사용.
- 일정 확정 시 `plan_to_legacy_schedule()` 결과를 `UserSettlementPlan.service_schedule`에 기록해 기존 달력/코드와 호환 유지.

---

## 4. Follow-up cleanup suggestions

1. **쿼리용 상수:** `status__in=(SettlementQuote.Status.FINAL_SENT, SettlementQuote.Status.PAID)`를 `settlement/constants.py`에 `CUSTOMER_VISIBLE_QUOTE_STATUSES` 등으로 두고, `config/views.py`, `schedule_utils.py`, `ai_agent/context_builder.py` 등에서 재사용하면 유지보수에 유리함 (선택).
2. **시그널 정리:** 견적/결제/일정 변경 시 메일·메시지를 시그널로 보내도록 할 경우, 한 곳에서만 발송되도록 설계해 알림 중복을 방지할 것.
3. **테스트 확장:** `survey.tests`, `settlement.tests`에 제출 → 견적 송부 → 결제 완료 → 일정 송부의 통합 시나리오 테스트를 추가하면 회귀 방지에 도움이 됨.
4. **i18n 키 정리:** 대시보드/달력/모달용 번역 키가 `config/views.dashboard_i18n` 등에 하드코딩되어 있음. 필요 시 `StaticTranslation` 또는 JSON으로 분리해 관리할 수 있음.

---

## 5. Remaining risks

1. **결제:** 현재는 mock 결제. 실제 PG 연동 시 `api_quote_checkout` 부근에서 결제 검증·멱등·실패 시 롤백 처리를 반드시 추가해야 함.
2. **이메일/SMTP:** 설정 미비 시 알림이 실패할 수 있음. 이미 로그/경고로 처리되어 있으나, 운영 시 `check_email_env` 및 재시도 정책 점검 권장.
3. **스케줄링 엔진:** 규칙 기반이며, Agent 가용 구간이 없을 때 fallback 동작과 “admin 검토 필요” 표시가 올바른지 실제 데이터로 주기적으로 확인하는 것이 좋음.
4. **AI 어시스턴트:** Stub 어댑터 사용 시 프로덕션 LLM/웹검색 연동 전에 보안·할당량·로그 보존 정책을 정리할 필요가 있음.
