# Step 12: 전체 플로우 점검 결과

## 1. 의도된 라이프사이클 추적

| 단계 | 설명 | 구현 위치 | 비고 |
|------|------|-----------|------|
| **1** | Admin이 설문 카드·문항 생성 | `survey/models.py` (SurveySection, SurveyQuestion), `survey/admin.py` (SurveySectionAdmin + SurveyQuestionInline) | 카드/섹션 없으면 기존 step 기반 동작 유지 |
| **2** | 고객이 카드 형식으로 설문 작성 | `survey/views.py` (survey_start, survey_step, survey_step_save), `templates/survey/survey_wizard.html` | `_get_sections_for_draft(draft)` → 카드별 단계, use_cards + current_section |
| **3** | 제출이 living request dossier로 유지 | `survey/models.py` (SurveySubmission.Status.REVISION_REQUESTED, revision_requested_at/message, SurveySubmissionEvent), `survey/views.py` (_get_or_create_draft가 DRAFT/REVISION_REQUESTED 반환) | 재제출 시 이벤트 resubmitted + resolved_section_ids |
| **4** | 구조화된 답변으로 견적 초안 자동 생성 | `survey/quote_input.py` (get_quote_input_data), `settlement/quote_draft.py` (generate_quote_draft_from_submission) | 설문 제출 시 DRAFT 없을 때만 자동 호출; Admin 액션으로도 호출 가능 |
| **5** | Admin이 raw가 아닌 요약된 요청 검토 | `config/views.py` (submission_review), `templates/app/submission_review.html` | 고객 요약, 요청 요약(정규화), 견적 초안, 워크플로우, 결제/일정, 자동 체크 |
| **6** | Admin이 필요한 곳만 구조화된 수정 요청 | `config/views.py` (submission_review_request_section_updates), `survey/models.py` (SurveySubmissionSectionRequest) | 카드별 수정 요청 + revision_requested_message |
| **7** | 고객이 지정된 카드만 수정 | `survey/views.py` (_get_sections_for_draft → pending section만 단계로), `survey_wizard.html` (sections_need_update_titles, locked_section_titles) | REVISION_REQUESTED + pending section_requests 시 해당 카드만 단계로 표시 |
| **8** | 견적 초안 갱신 | `survey/views.py` (survey_submit: was_revision이면 generate_quote_draft_from_submission 호출) | 재제출 시 항상 draft 재생성 |
| **9** | Admin이 최종 승인 후 고객에게 송부 | `settlement/quote_approval.py` (finalize_and_send_quote), `config/views.py` (submission_review_approve_quote), `settlement/admin.py` (save_model에서 동일 함수 호출) | URL: `admin/review/<id>/approve-quote/` |
| **10** | 고객 결제 | `settlement/views.py` (_process_quote_checkout, api_quote_checkout) | PAID 설정, submission → AGENT_ASSIGNMENT, UserSettlementPlan, PlanServiceTask 생성 |
| **11** | 결제 후 스케줄/에이전트 준비 | `settlement/post_payment.py` (build_initial_schedule_from_quote, ensure_plan_service_tasks), `settlement/views.py` (_process_quote_checkout 내 호출), `settlement/views.py` (api_appointment_request에서 PlanServiceTask.appointment 연결) | entry_date 반영 일정, PlanServiceTask로 필요 작업 노출 |
| **12** | Admin이 최종 스케줄 확인 | `config/views.py` (submission_review의 scheduling_summary, required_tasks), Django Admin (AgentAppointmentRequest, PlanServiceTask, UserSettlementPlan) | 에이전트 확정 = 스케줄 확정; Admin은 조회·관리만 |

---

## 2. 점검 결과

### 2.1 마이그레이션

- **survey**: `0003`(섹션/문항 메타), `0004`(revision/events), `0005`(quote 메타), `0006`(SurveySubmissionSectionRequest) — 의존성 순서 정상.
- **settlement**: `0015`(draft_source, auto_generated_at), `0016`(PlanServiceTask) — 0015 → 0016 순서 정상.
- **누락 마이그레이션**: 없음. 적용 명령: `python manage.py migrate survey settlement`.

### 2.2 URL

- **설문**: `settlement/survey/`, `.../step/<n>/`, `.../step/<n>/save/`, `.../submit/`, `.../thankyou/` — 모두 `survey/urls.py`에 정의되어 있으며, `survey_start`/`survey_submit` 등에서 `reverse('survey:...')` 사용 정상.
- **검토**: `admin/review/`, `admin/review/<id>/`, `.../request-revision/`, `.../request-section-updates/`, `.../generate-draft/`, `.../approve-quote/` — `config/urls.py`에 정의됨.
- **깨진 URL**: 없음.

### 2.3 권한

- **Admin 검토**: `submission_review_list`, `submission_review`, `request_revision`, `request_section_updates`, `generate_draft`, `approve_quote` — 모두 `@login_required` + `@user_passes_test(_staff_required)` 적용. 비스태프는 `/login/`으로 리다이렉트.
- **설문**: `ensure_csrf_cookie`만 사용, 로그인 필수 아님(비로그인 설문 가능).
- **결제/견적**: 기존 정책 유지(고객만 결제, FINAL_SENT 이상만 가격 노출).

### 2.4 하위 호환성

- **섹션 없는 문항**: `SurveyQuestion.section` nullable, `_get_sections_with_questions()`가 빈 리스트를 반환하면 `_get_step_list()`가 `SurveyQuestion.step` 기준 단계 사용 — 기존 step 기반 설문 유지.
- **기존 제출**: section_requests 없으면 `_get_sections_for_draft()`가 전체 섹션 반환; quote_draft 없어도 `run_submission_checks()`는 동작하며 `has_draft` 실패로 incomplete로 표시.
- **기존 견적**: `draft_source`/`auto_generated_at` 빈 값 허용, 기존 SettlementQuote 동작 유지.

### 2.5 기존 제출(legacy) 영향

- 기존 제출은 `SurveySection`/`SurveySubmissionSectionRequest` 없이도 조회·상세 표시 가능.
- `get_quote_input_data(submission)`는 `quote_relevant` 문항만 사용하므로, 기존 answers 구조만 맞으면 동작.
- 결제 완료된 건은 이미 `UserSettlementPlan` 존재; `PlanServiceTask`는 결제 시점에만 생성되므로 기존 플랜에는 없을 수 있음 — 검토 페이지에서 `required_tasks` 빈 리스트로 표시되며 오류 없음.

### 2.6 자동화를 막는 free-text 의존

- **구조화 우선**: 카드별 수정은 `SurveySubmissionSectionRequest`(섹션 단위)로만 요청; 고객은 해당 카드만 재입력.
- **견적 입력**: `get_quote_input_data()`가 `quote_relevant` + `quote_mapping_key` 기반으로 정규화; `special_requirements`는 참고용이며 견적 자동 생성의 필수 조건이 아님.
- **자동 체크**: `survey/submission_checks.py`는 이메일, 서비스 코드 존재·등록 여부, 초안 갱신 시점, _needs_review 등 규칙 기반만 사용. free-text로 “승인 가능”을 막지 않음.

### 2.7 남는 수동 포인트

- **가격/미등록 코드**: `_needs_review` 항목·미등록 서비스 코드는 여전히 Admin이 Django Admin 또는 검토 페이지에서 가격 입력·코드 등록 필요.
- **최종 “스케줄 확정”**: 에이전트가 약속을 확정하면 곧 확정으로 간주; Admin이 별도 “최종 확정” 버튼을 누르는 단계는 없음(의도된 설계).
- **이메일/알림**: 송부·결제 등은 자동이지만, SMTP/설정 미비 시 실패 시 조용히 넘어가므로 운영 모니터링 권장.

---

## 3. 최종 변경 파일 목록

### 3.1 신규 파일

| 파일 | 용도 |
|------|------|
| `survey/quote_input.py` | 견적 입력 정규화 (get_quote_input_data) |
| `survey/submission_checks.py` | 제출/견적 자동 체크 (run_submission_checks) |
| `settlement/quote_draft.py` | 견적 초안 자동 생성 |
| `settlement/quote_approval.py` | 최종 승인·송부 공통 로직 |
| `settlement/post_payment.py` | 결제 후 일정·PlanServiceTask 준비 |
| `templates/app/submission_review_list.html` | 제출 목록(검토용) |
| `templates/app/submission_review.html` | 제출 단건 검토(요약·견적·체크·조치) |
| `docs/WORKFLOW_REVIEW_STEP12.md` | 본 점검 문서 |

### 3.2 수정된 파일

| 파일 | 주요 변경 |
|------|------------|
| `survey/models.py` | SurveySection, SurveySubmission 이벤트/리비전, SurveySubmissionSectionRequest, SurveyQuestion 메타(섹션/quote_relevant/quote_mapping_key 등) |
| `survey/views.py` | 카드별 단계·pending section, draft 기준 step/questions/section, 제출 시 section 해결·draft 재생성 |
| `survey/admin.py` | SurveySectionAdmin, 문항 메타·인라인, 제출 이벤트/섹션요청 인라인, 액션(수정 요청·견적 초안 생성) |
| `settlement/models.py` | SettlementQuote(draft_source, auto_generated_at), PlanServiceTask |
| `settlement/admin.py` | 견적 draft_source/재생성 액션, save_model → quote_approval, PlanServiceTask 인라인·Admin |
| `settlement/views.py` | _build_plan_schedule → post_payment, 결제 시 ensure_plan_service_tasks, 약속 생성 시 PlanServiceTask.appointment 연결 |
| `settlement/constants.py` | quote_for_customer에서 _auto/_needs_review 제거 |
| `config/views.py` | submission_review_list, submission_review, request_revision, request_section_updates, generate_draft, approve_quote, 자동 체크 연동 |
| `config/urls.py` | admin/review/* URL 및 뷰 import |
| `templates/app/admin_dashboard.html` | 설문 제출 검토 링크 |
| `templates/survey/survey_wizard.html` | 카드 UI, 수정 요청 시 수정할/잠긴 카드 안내 |

### 3.3 마이그레이션 파일

| 앱 | 마이그레이션 | 내용 |
|----|--------------|------|
| survey | 0003_survey_section_and_question_metadata | SurveySection, SurveyQuestion 섹션/메타 필드 |
| survey | 0004_request_dossier_revision_and_events | 리비전 필드, SurveySubmissionEvent |
| survey | 0005_quote_metadata_for_automation | quote_mapping_key, quote_value_type |
| survey | 0006_survey_submission_section_request | SurveySubmissionSectionRequest |
| settlement | 0015_quote_draft_source_and_auto_generated_at | draft_source, auto_generated_at |
| settlement | 0016_plan_service_task | PlanServiceTask |

---

## 4. 수동 QA 체크리스트

- [ ] **마이그레이션**: `python manage.py migrate survey settlement` 성공, 롤백 없음.
- [ ] **Admin 설문**: Survey Section/Question CRUD, 카드별 문항 순서·quote_relevant·quote_mapping_key 저장.
- [ ] **고객 설문**: 비로그인/로그인 각각 설문 시작 → 카드(또는 step) 진행 → 저장 → 제출 → thankyou.
- [ ] **이미 제출된 고객**: 동일 계정으로 `/settlement/survey/` 접속 시 “이미 제출됨” 페이지.
- [ ] **Admin 검토 목록**: `/admin/review/` 스태프만 접근, 제출 목록·페이징.
- [ ] **Admin 검토 상세**: 제출 선택 → 요약·견적 초안·자동 체크·준비도 뱃지 표시.
- [ ] **자동 체크**: 이메일/서비스 유무, 미등록 코드, 고객 대기, 초안 신선도, _needs_review 반영되는지.
- [ ] **카드별 수정 요청**: 검토 페이지에서 카드 선택 후 “선택 카드 수정 요청” → 제출 상태 REVISION_REQUESTED, 고객 설문에서 해당 카드만 단계로 표시.
- [ ] **고객 재제출**: 수정 후 제출 → section_requests 해결, 견적 초안 재생성, SUBMITTED.
- [ ] **견적 초안 생성**: 검토 페이지 “견적 초안 자동 생성” 또는 설문 제출 시(초안 없을 때) 생성.
- [ ] **승인 후 송부**: “승인 후 고객에게 송부” → quote FINAL_SENT, submission AWAITING_PAYMENT, 이메일 발송, sent_at 설정.
- [ ] **고객 견적/결제**: 내 견적 페이지에서 FINAL_SENT 견적 확인 후 결제 → PAID, UserSettlementPlan·PlanServiceTask 생성.
- [ ] **결제 후 일정**: 검토 페이지 “일정 준비도”·“필요 작업” 테이블, Django Admin에서 PlanServiceTask·AgentAppointmentRequest 확인.
- [ ] **에이전트 배정**: 고객이 전담 에이전트 선택·약속 요청 → AgentAppointmentRequest 생성 시 해당 PlanServiceTask.appointment 연결.
- [ ] **비스태프**: `/admin/review/` 접근 시 로그인 페이지로 리다이렉트.

---

## 5. 권장 후속 개선

1. **이메일/알림 모니터링**: 송부·리마인더 실패 시 Admin 대시보드 또는 로그 요약으로 노출.
2. **견적 초안 “갱신 권장” 자동 표시**: `draft_fresh` 실패 시 검토 페이지에서 “초안 재생성” 버튼 강조 또는 배지.
3. **제출 목록 필터**: 상태(SUBMITTED/REVISION_REQUESTED 등), 준비도(ready_for_approval 등)로 필터링.
4. **PlanServiceTask 대량 생성**: 이미 결제된 플랜에 대해 과거 PAID 견적로 한 번에 PlanServiceTask backfill (선택).
5. **번역**: 검토 페이지·자동 체크 메시지 등에 i18n 키 적용 후 번역 파이프라인 연동.
6. **테스트**: `run_submission_checks`, `get_quote_input_data`, `generate_quote_draft_from_submission`, `finalize_and_send_quote` 등에 단위/통합 테스트 추가.
