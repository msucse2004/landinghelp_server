# 설문 수정 요청 → 추천 페이지 → 수정 저장 추적 흐름 분석

목표: 사용자 텍스트 수정 요청 → 휴리스틱/LLM 추천 페이지 → 사용자 이동 → **실제 수정 저장한 페이지 추적** → 학습용 feedback 로그 저장

---

## 1. 관련 파일 경로 정리

### 1.1 사용자 메시지 수신 · 진입점

| 역할 | 파일 경로 | 설명 |
|------|-----------|------|
| 메시지 POST API | `messaging/views.py` | `api_conversation_messages()` POST: 메시지 저장 후 `handle_customer_request_flow('messaging_inbox', ...)` 호출 |
| 견적 수정 경로 | `settlement/views.py` | 고객 견적 수정 요청 시 `handle_customer_request_flow` 호출 (channel 등 다름) |
| 통합 진입 · 컨텍스트 | `customer_request_service.py` | `intake_customer_request()`, `_intake_messaging()`, `_intake_quote_revision()` — conversation, message, submission, policy 세팅 |

### 1.2 휴리스틱 분류

| 역할 | 파일 경로 | 설명 |
|------|-----------|------|
| 휴리스틱 정책 | `customer_request_policy.py` | `_heuristic_policy()`, `_HEURISTIC_PATTERNS` (regex → Intent, confidence, customer_summary 등) |
| 서비스 변경 패턴 | `customer_request_policy.py` | `_RE_SERVICE_CHANGE` 등 — "서비스 변경/수정" → `SURVEY_REOPEN_REQUEST`, `target_section_ids`는 휴리스틱에서는 비어 있음 |

### 1.3 LLM 분석

| 역할 | 파일 경로 | 설명 |
|------|-----------|------|
| 분류 파이프라인 | `customer_request_policy.py` | `classify_customer_request()` — Heuristic → Ollama → Gemini 순 호출 |
| LLM 호출 · 프롬프트 | `customer_request_llm.py` | `call_ollama_classify()`, `call_gemini_classify()`, `_call_single_adapter()`, compact/full 프롬프트, `target_survey_section_ids` 파싱 |
| 정책 결과 저장 | `customer_request_service.py` | `_save_intent_analysis()` — `CustomerRequestIntentAnalysis` 생성 (conversation, message, customer, predicted_intent, **target_section_ids** 등) |

### 1.4 추천 페이지(라우팅) · 설문 열기

| 역할 | 파일 경로 | 설명 |
|------|-----------|------|
| 설문 시작(진입) | `survey/views.py` | `survey_start()` — `?resume=1` 시 DRAFT/REVISION_REQUESTED 초안으로 리다이렉트, **step = 첫 단계 또는 pending section 기준** |
| 단계/섹션 목록 | `survey/views.py` | `_get_sections_for_draft()`, `_get_step_list()` — REVISION_REQUESTED + section_requests 있으면 **요청된 섹션만** step 목록으로 사용 |
| 섹션 요청 생성 | `customer_request_service.py` | `_create_section_requests_for_submission()` — `target_section_ids`(휴리스틱 기본값 "희망 서비스" 또는 LLM) → `SurveySubmissionSectionRequest` |
| 설문 편집 URL | `messaging/views.py`, `config/views.py` 등 | `survey_edit_url` = `reverse('survey:survey_start') + '?resume=1'` (step 쿼리 없음, 서버에서 step 결정) |

### 1.5 설문 수정 저장 API

| 역할 | 파일 경로 | 설명 |
|------|-----------|------|
| 단계별 저장 | `survey/views.py` | `survey_step_save()` — POST `survey/step/<n>/save/` → answers, current_step 갱신, **어느 step에서 저장했는지 DB에는 current_step만 반영** |
| 최종 제출 | `survey/views.py` | `survey_submit()` — POST `survey/submit/` → SUBMITTED, `_log_submission_event()`, 재제출 시 `record_followup_success()` 호출 |

### 1.6 Feedback / 버튼 클릭 / 이벤트 로그

| 역할 | 파일 경로 | 설명 |
|------|-----------|------|
| 액션 피드백 로그 모델 | `messaging/models.py` | `CustomerActionFeedbackLog` — proposal FK, event_type, event_payload(JSON), actor, created_at |
| 피드백 기록 | `customer_request_service.py` | `_log_feedback()` — PROPOSAL_SHOWN, USER_CONFIRMED, USER_DECLINED, ACTION_STARTED, ACTION_SUCCEEDED, ACTION_FAILED, USER_CORRECTED, FOLLOWUP_SUCCESS, PROPOSAL_EXPIRED 등 |
| 학습 신호 payload | `customer_request_service.py` | `_build_learning_signal()` — predicted_intent, predicted_action, confidence, source, action_code, user_feedback, final_outcome, original_text, followup_text 등 |
| 제안 노출/확인/거절 API | `settlement/views.py` | `api_proposal_confirm()`, `api_proposal_decline()`, `api_proposal_mark_shown()` — confirm 시 `confirm_proposal()` → 실행 후 redirect는 **프론트에서 survey_edit_url로** 처리 |
| 설문 제출 이벤트 | `survey/models.py` | `SurveySubmissionEvent` — event_type: submitted, resubmitted, revision_requested, reopened 등, meta(JSON) |
| 설문 이벤트 기록 | `survey/views.py` | `_log_submission_event()` — 제출/재제출 시 호출, `SurveySubmissionEvent` 생성 |

### 1.7 기타 관련

| 역할 | 파일 경로 | 설명 |
|------|-----------|------|
| 제안(Proposal) 모델 | `messaging/models.py` | `CustomerActionProposal` — analysis FK, action_code, conversation, submission, **target_section_ids는 analysis에 있음** |
| 분류 결과 모델 | `messaging/models.py` | `CustomerRequestIntentAnalysis` — customer, conversation, message, predicted_intent, **target_section_ids** |
| 후속 성공 기록 | `customer_request_service.py` | `record_followup_success()` — 설문 재제출 시 최근 EXECUTED reopen_survey proposal에 FOLLOWUP_SUCCESS 로그 (resolved_section_ids 등 event_meta 전달) |

---

## 2. 현재 데이터 흐름 요약

1. **메시지 수신**  
   메시지함 POST → `messaging/views.py` → `handle_customer_request_flow('messaging_inbox', user, text, conversation=..., message=...)`

2. **분류**  
   `intake_customer_request()` → `analyze_customer_request()` → `classify_customer_request()`  
   → 휴리스틱 먼저, 필요 시 Ollama → Gemini, `PolicyResult` (detected_intent, **target_section_ids** 등) 반환.

3. **분석 저장**  
   `_save_intent_analysis()` → `CustomerRequestIntentAnalysis` 생성 (original_text, predicted_intent, **target_section_ids**, source, confidence 등).

4. **제안 생성 및 라우팅 준비**  
   AUTO_CONFIRMABLE이면 `_create_action_proposal()` → `CustomerActionProposal` 생성.  
   `target_section_ids` 비어 있으면 서비스 수정 시 "희망 서비스" 섹션 ID로 `_create_section_requests_for_submission()` 호출 → `SurveySubmissionSectionRequest` 생성.

5. **사용자 이동**  
   고객이 "설문 수정하기" 클릭 → `api_proposal_confirm()` → `confirm_proposal()` → reopen_survey 실행(REVISION_REQUESTED 등).  
   프론트는 응답 후 `survey_edit_url`(예: `/settlement/survey/?resume=1`)로 이동.  
   `survey_start()`에서 pending section_requests 기준으로 **첫 step** 결정 후 `survey/step/<step>/`로 리다이렉트.

6. **저장**  
   - **단계 저장**: `survey_step_save(step)` — POST로 step별 저장, `draft.current_step` 갱신. **“어느 step에서 저장했는지”는 current_step에만 있고, “이 저장이 수정 요청 흐름의 어떤 제안/분류와 연결됐는지”는 기록하지 않음.**  
   - **최종 제출**: `survey_submit()` — 재제출 시 `_log_submission_event(..., 'resubmitted', meta={resolved_section_ids, ...})`, `record_followup_success(submission, event_meta)` → 최근 EXECUTED reopen_survey proposal에 **FOLLOWUP_SUCCESS** 한 건만 기록 (event_payload에 followup_event, resolved_section_ids 등).

7. **현재 feedback 로그**  
   - `CustomerActionFeedbackLog`: 제안 노출/승인/거절/실행 시작·성공·실패/고객 정정/후속 성공 등. **어느 설문 step에서 저장·제출했는지는 없음.**  
   - `SurveySubmissionEvent`: 제출/재제출/수정요청 등. **어느 step에서 마지막으로 수정했는지, 추천 step과의 일치 여부는 없음.**

---

## 3. 목표 기능 대비 부족한 부분

| 목표 | 현재 상태 | 부족한 점 |
|------|-----------|-----------|
| 1. 사용자 수정 요청 수신 | ✅ 구현됨 | - |
| 2. 휴리스틱/LLM으로 수정 목적 페이지 추천 | ✅ 구현됨 | 추천은 section_id(s) / step으로 반영되나, “추천 step”이 단일 값으로 명시 저장되지는 않음 (section_requests로만 유도). |
| 3. 사용자가 추천 페이지로 이동 | ✅ 구현됨 | resume=1 → 서버가 section_requests 기준 첫 step으로 리다이렉트. |
| 4. **어느 페이지(step)에서 수정 저장했는지 추적** | ⚠️ 부분적 | `survey_step_save()`는 `current_step`만 갱신. **“이번 세션에서 마지막으로 저장한 step”을 제안/분석과 연결해 기록하지 않음.** 재제출 시 `record_followup_success()`는 호출되지만 **step 정보 없음.** |
| 5. **학습용 feedback 로그에 위 데이터 저장** | ⚠️ 부분적 | `CustomerActionFeedbackLog`에 predicted_intent, original_text, user_feedback, final_outcome 등은 있음. **추천 step(s) / 실제 수정한 step(s) / 일치 여부** 필드는 없음. |

---

## 4. 수정 계획 제안 (코드 변경 없이 설계만)

### 4.1 “실제 수정한 페이지” 추적

- **저장 위치 후보**  
  - **A)** `SurveySubmissionEvent`: event_type 예: `step_saved` 또는 기존 `resubmitted`의 meta에 `last_saved_step`, `saved_steps` 등 추가.  
  - **B)** `CustomerActionFeedbackLog`: FOLLOWUP_SUCCESS 또는 새 event_type(예: `SURVEY_STEP_SAVED`)에 `saved_step`, `recommended_section_ids` 등을 event_payload에 포함.  
  - **C)** 별도 모델: 예) `SurveyRevisionEditLog` (submission, proposal 또는 analysis FK, step, section_id, saved_at 등).  

- **데이터 채우는 시점**  
  - **단계 저장 시**: `survey_step_save()` 내부에서 REVISION_REQUESTED이고, 해당 submission에 대한 최근 EXECUTED reopen_survey proposal이 있으면, 그 proposal(또는 analysis)과 현재 `step`(및 section_id)를 연결해 로그/이벤트 기록.  
  - **최종 제출 시**: `survey_submit()`의 `record_followup_success()` 호출 시 `event_meta`에 **실제로 수정이 발생한 step 목록**(또는 last_saved_step)을 넣어 전달. (현재는 `resolved_section_ids`만 전달.)

### 4.2 수정 시 수정할 파일 (계획)

| 순서 | 파일 | 내용 |
|------|------|------|
| 1 | `survey/views.py` | `survey_step_save()`: REVISION_REQUESTED일 때, 해당 submission의 최근 EXECUTED reopen_survey proposal 조회 후, step/section_id를 이벤트 또는 feedback 로그에 기록. (선택) `_log_submission_event()`에 step_saved 유형 추가 또는 meta 확장. |
| 2 | `survey/views.py` | `survey_submit()`: 재제출 시 `event_meta`에 `last_saved_step` 또는 `saved_steps`(현재 draft.current_step 또는 별도 추적값) 포함해 `record_followup_success(submission, event_meta=...)` 호출. |
| 3 | `customer_request_service.py` | `record_followup_success()`: `event_meta`에서 `saved_step`/`saved_steps`/`resolved_section_ids`를 받아 `_log_feedback(..., payload=...)`에 **recommended_section_ids**(analysis.target_section_ids 또는 section_requests 기준)와 **actual_saved_step(s)** 를 넣어 학습용 payload 보강. |
| 4 | `customer_request_service.py` | `_build_learning_signal()` 또는 feedback 로그 payload 구조: **recommended_step / recommended_section_ids**, **actual_saved_step / actual_saved_section_ids**, **match**(일치 여부) 필드 정의. (필요 시 `CustomerActionFeedbackLog.event_payload` 스키마 문서화.) |
| 5 | `messaging/models.py` | (선택) `CustomerActionFeedbackLog`에 `event_type` 새 값 추가 예: `SURVEY_STEP_SAVED` — 단계 저장 시점에만 기록하고, 재제출 시 FOLLOWUP_SUCCESS에 요약 포함. |
| 6 | `survey/models.py` | (선택) `SurveySubmissionEvent.EventType`에 `step_saved` 추가 및 meta에 step, section_id 등 정의. |

### 4.3 휴리스틱/LLM “추천 step” 명시 저장 (선택)

- `CustomerRequestIntentAnalysis`에 이미 `target_section_ids` 있음.  
- “추천 step”을 하나의 숫자로 쓰고 싶다면: section_requests의 첫 번째 section의 display_order 또는 step 매핑을 분석 저장 시점에 계산해 `analysis` 또는 proposal의 payload에 `recommended_step`으로 넣어 두면, 나중에 actual_saved_step과 비교하기 쉬움.  
- 수정 파일: `customer_request_service.py` (`_save_intent_analysis()` 또는 `_create_section_requests_for_submission()` 호출 직후), 또는 분석/제안을 조회하는 쪽에서 section → step 변환 후 payload에만 넣어도 됨.

---

## 5. 요약

- **메시지 수신·분류·제안 생성·설문 열기·단계/최종 제출**까지의 경로와 관련 파일은 위와 같다.  
- **부족한 부분**: (1) 단계 저장 시 “어느 step에서 저장했는지”를 제안/분석과 연결한 기록이 없음, (2) 재제출 시 feedback에 “추천 section/step”과 “실제 수정한 step”이 함께 남지 않음.  
- **제안**: `survey_step_save` / `survey_submit` / `record_followup_success` / feedback payload 스키마를 위와 같이 확장하면, “사용자가 추천 페이지로 이동했는지, 실제로 어디서 수정 저장했는지”를 학습용 feedback 로그에 남길 수 있다.
