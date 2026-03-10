# 고객 메시지 기반 요청 처리/설문·견적 수정 플로우 재정비 설계안

## 배경 및 목표
현재 프로젝트는 **설문 재개(고객 재수정)**, **견적 수정 요청(LLM 분석 기반)**, **메시지함 UI 버튼 노출**, **고객 대시보드/견적 화면 CTA**가 서로 다른 위치에서 개별적으로 구현되어 있습니다.  
이번 재정비의 목적은 다음을 만족하는 **단일 정책 엔진 + 명확한 상태기계 + 버튼 기반 실행(사용자 확인 후 실행)** 아키텍처를 정의하는 것입니다.

- **고객이 설문 제출 후에도 수정 진입점이 있다.**
- **고객 텍스트 메시지는 LLM이 분석**하고, 결과에 따라 **자동 응답 + 버튼(액션 제안)**을 제공한다.
- 버튼이 있는 액션은 **클릭 전에는 실행되지 않는다**(실행은 항상 명시적 사용자 확인 후).
- Admin이 **고객 요청 없이도** 설문 수정 가능 상태를 열 수 있다.
- 견적 송부 이후에도 고객이 메시지함에서 수정 요청을 보내면 **동일한 정책 엔진**으로 처리된다.
- 상태기계는 **(1) SurveySubmission**, **(2) QuoteChangeRequest(견적 변경 워크플로우)**, **(3) CustomerActionProposal(고객 액션 제안/버튼 상태)**를 **분리**한다.
- 메시지함/고객 대시보드/customer quote가 **동일한 정책 엔진**을 사용한다.

---

## 분석 대상 파일 및 현재 구조 요약
### `survey/models.py`
- `SurveySubmission.Status`: `DRAFT → SUBMITTED → REVISION_REQUESTED → SUBMITTED → AWAITING_PAYMENT → AGENT_ASSIGNMENT → SERVICE_IN_PROGRESS`
- 고객 편집 가능 여부는 `SurveySubmission.can_customer_edit()`로 결정: `DRAFT` 또는 `REVISION_REQUESTED`만 True
- 이벤트 로그: `SurveySubmissionEvent` (submitted/resubmitted/revision_requested/reopened/quote_sent/paid/…)
- 카드별 수정 요청: `SurveySubmissionSectionRequest` (특정 섹션만 수정 요청 가능)

### `survey/views.py`
- `survey_start`는 `?resume=1` 진입을 지원(비로그인 시 로그인 유도).
- 재작성/재개는 “편집 가능 상태”(`DRAFT`, `REVISION_REQUESTED`)를 기준으로 draft를 찾음.
- `survey_submit`는 `DRAFT` 또는 `REVISION_REQUESTED`에서 `SUBMITTED`로 전환(재제출 포함).
- 재제출(was_revision) 시 `QuoteChangeRequest.Status.CUSTOMER_ACTION_REQUIRED → IN_REVIEW`로 업데이트하는 로직이 존재.

### `settlement/models.py`
- `SettlementQuote.Status`: `DRAFT / NEGOTIATING / FINAL_SENT / PAID`
- `revision_superseded_at`로 기존 FINAL_SENT 견적을 “삭제하지 않고 결제만 차단”하는 정책.
- `QuoteChangeRequest` + `QuoteChangeAnalysis` + `QuoteChangeActionLog`로 견적 변경 요청 워크플로우를 관리.
  - `QuoteChangeRequest.can_be_reopened_for_survey_edit()`는 **submission이 `SUBMITTED` 또는 `AWAITING_PAYMENT`**일 때만 설문 재개 승인 가능(서비스 진행 단계로 되돌림 방지).

### `settlement/services_quote_change.py`
- 자유 텍스트 견적 변경 요청: `submit_text_change_request(quote, user, message)`
  - `QuoteChangeRequest` 생성(OPEN) → LLM 분석 → `ANALYZED`
- Admin 설문 재개 승인: `approve_reopen_survey(change_request, admin_user)`
  - `SurveySubmission.status → REVISION_REQUESTED`
  - `QuoteChangeRequest.status → CUSTOMER_ACTION_REQUIRED`
  - 기존 `FINAL_SENT` 견적 `revision_superseded_at` 설정(결제 차단)
  - 고객 메시지 발송(`send_survey_reopened_customer_message`)

### `settlement/services_quote_change_llm.py`
- “견적 변경 요청”에 대한 LLM 분류/액션 제안 스키마가 이미 존재:
  - intent: `QUOTE_ITEM_CHANGE_REQUEST / SURVEY_REOPEN_REQUEST / GENERAL_QUESTION / UNSUPPORTED_REQUEST / URGENT_ADMIN_REVIEW`
  - action_type: `PROPOSE_ADD_SERVICE / PROPOSE_REMOVE_SERVICE / PROPOSE_CHANGE_SERVICE / PROPOSE_REOPEN_SURVEY / PROPOSE_ADMIN_REPLY_ONLY / PROPOSE_MANUAL_REVIEW`
- 중요한 특징: **이 서비스는 DB 상태를 바꾸지 않고 분석 결과만 만든다.**

### `messaging/views.py`
- 현재 “고객 메시지 기반 설문 재개”는 **LLM 없이 휴리스틱으로 즉시 실행**:
  - `_maybe_reopen_survey_from_customer_message`는
    - 메시지 본문에 “설문 + 수정” 키워드가 있으면
    - `SurveySubmission.status`를 **즉시 `REVISION_REQUESTED`로 변경**하고
    - 자동 안내 답장을 발송함
  - 실행 허용 상태는 `SUBMITTED` 또는 `AWAITING_PAYMENT`로 제한(최근 수정).
- 즉, 메시지 입력(POST) 시점에 **버튼 클릭 없이 상태가 바뀌는 경로**가 존재.

### UI: `templates/messaging/inbox.html`
- 고객: `api_conversation_detail`의 `show_survey_edit_button`일 때 하단에 “설문 수정하기” 버튼 노출.
- Admin: `survey_review_url`이 있으면 “고객 설문 확인” 버튼 노출.

### UI: `templates/services/customer_quote.html`
- 고객이 “견적서 수정 요청” 텍스트를 입력하면 `api_settlement_quote_request_revision`으로 POST
  - 이는 `QuoteChangeRequest` + LLM 분석 플로우로 연결됨(버튼 기반 실행이 아님: ‘전송’은 즉시 분석/접수).
- `CUSTOMER_ACTION_REQUIRED`이면 “설문 다시 수정하기” CTA 노출(`survey_resume_url`).
- `quote_superseded`이면 결제 차단 + 설문 수정 CTA 노출.

### UI: `templates/app/customer_dashboard.html` 및 `config/views.py`(dashboard)
- `show_reopen_survey`가 True이면 “설문 다시 수정하기” 링크를 `survey_resume_url`로 노출.
- `survey_resume_url = reverse('survey:survey_start') + '?resume=1'`

---

## 현재 구현에서의 “고객 메시지 기반 수정 요청” vs “견적 수정 요청(LLM)” 차이
### 1) 트리거와 실행 시점
- **메시지 기반 설문 수정 요청(`messaging/views.py`)**
  - 트리거: 고객이 메시지함에서 메시지 전송(POST)
  - 실행: 서버가 **즉시** `SurveySubmission.status = REVISION_REQUESTED`로 변경(자동 실행)
  - 고객 확인(버튼 클릭) 없이 실행되는 “즉시 상태 변경 경로”가 존재

- **견적 수정 요청(`customer_quote.html` → `api_settlement_quote_request_revision` → `services_quote_change.py`)**
  - 트리거: 고객이 “견적서 수정 요청” textarea에 입력 후 버튼 클릭
  - 실행: `QuoteChangeRequest` 생성 + LLM 분석(즉시)
  - 단, **설문 재개(REVISION_REQUESTED)는 Admin 승인**(`approve_reopen_survey`)이 있어야 실행

### 2) 분류/정책 엔진 존재 여부
- 메시지 기반 로직은 LLM/정책 엔진이 아니라 **키워드 휴리스틱**(설문+수정)으로 단일 케이스만 처리.
- 견적 수정 요청은 LLM 스키마/검증/저장(QuoteChangeAnalysis)이 이미 있고, intent/action 개념이 존재.

### 3) 데이터 모델링
- 견적 수정 요청은 `QuoteChangeRequest`(상태 포함)로 추적 가능(감사 로그 포함).
- 메시지 기반 설문 재개는 “요청 객체”가 없고, `SurveySubmissionEvent`만 남음.  
  → 고객 요청/제안/버튼/실행 여부를 **일관되게 추적하기 어렵다.**

---

## 중복/충돌/불안정 지점(왜 불안정할 수 있는가)
### 중복된 “설문 재개” 실행 경로
- Admin 승인 경로: `settlement/services_quote_change.py::_do_approve_reopen_survey`
- 고객 메시지 자동 실행 경로: `messaging/views.py::_maybe_reopen_survey_from_customer_message`
- 결과적으로 “설문 재개”가 **서로 다른 정책/조건/로그/메시지 형태**로 실행될 수 있음.

### 버튼 기반 실행 요구사항과 충돌
요구사항 7) “버튼 기반 액션은 클릭했을 때만 실제 실행”인데,  
현재 `messaging/views.py`는 고객 메시지 수신 즉시 설문을 `REVISION_REQUESTED`로 바꾸는 “즉시 실행”을 합니다.  
이 경로는 **정책 엔진 통합(요구사항 11)** 및 **상태기계 분리(요구사항 10)**에도 역행합니다.

### UI/상태 판단 로직이 분산되어 드리프트(규칙 불일치) 위험
- “설문 수정 가능 여부”는
  - 메시지함: `api_conversation_detail`에서 `submission.status == REVISION_REQUESTED`일 때 버튼 노출
  - 대시보드: `show_reopen_survey = (sub.status == REVISION_REQUESTED)`로 버튼 노출
  - customer quote: `CUSTOMER_ACTION_REQUIRED` / `quote_superseded` / `show_customer_action_cta` 등 여러 조건으로 CTA 노출
- 이처럼 화면별로 조건이 분산되면, 요구사항 변경 시 **일부 화면만 업데이트되어 불일치**가 생기기 쉽습니다.

### 메시지 기반 요청 처리의 범위/모델이 협소
- 고객 메시지 기반 처리: “설문 수정” 1종 휴리스틱만 존재
- 견적 화면 기반 처리: QuoteChangeRequest 중심(견적 변경 관점)
- 결과적으로 “설문 링크 다시 주세요”, “견적서 다시 보내주세요”, “일정 변경” 등 요구사항의 주요 케이스가 **통합된 방식으로 처리되지 않음**.

---

## 목표 아키텍처(권장)
핵심은 **(A) 메시지 분석(LLM) → (B) 액션 제안(버튼) → (C) 사용자 확인(클릭) → (D) 실행(Executor) → (E) 상태/로그 갱신**을 단일 흐름으로 만드는 것입니다.

### 구성 요소
1) **Request Analyzer**
- 입력: (conversation_id, message_id, customer_text, 컨텍스트: submission/quote/status)
- 출력: 분류 결과 + 추천 액션 목록 + 자동 응답 텍스트(안내)
- 구현: 기존 `settlement/services_quote_change_llm.py`를 확장하거나 새 모듈로 일반화

2) **Policy Engine (Single Source of Truth)**
- 입력: analyzer 결과 + 현재 상태(Submission/Quote/Appointment/ChangeRequest)
- 출력: “제안할 버튼(액션)”과 “실행 가능 조건” (예: 현재 상태에서 가능한지)
- 메시지함/대시보드/견적 화면은 모두 policy engine의 결과만 사용해 CTA를 렌더링

3) **CustomerActionProposal (새 상태기계/모델)**
- 고객에게 “버튼으로 제안된 액션”을 추적하는 별도 엔티티
- 실행 전/후, 만료, 취소, 중복 등을 안정적으로 관리

4) **Action Executor**
- 버튼 클릭(Confirm) 시에만 실행
- 실행은 idempotent(중복 클릭/재시도 안전)
- 실행 후 관련 상태기계 업데이트(Submission/Quote/ChangeRequest/Conversation 메시지)

---

## Intent taxonomy (LLM 분류: 요구사항 3)
요구사항의 3분류를 시스템의 “상위 분류”로 정의합니다.

### 1) `AUTO_CONFIRMABLE`
- 시스템이 처리 가능하지만 **고객 버튼 클릭 후 실행**해야 하는 요청
- 예:
  - 설문 다시 수정(재개)
  - 설문 링크 재발송(= `survey_start?resume=1` 안내)
  - 견적서 재송부(이메일/앱 메시지 재발송)
  - “이전 제출 내용을 다시 바꾸고 싶다”(= 설문 재개)

### 2) `HUMAN_REVIEW_REQUIRED`
- Admin/Agent 검토가 필요한 요청(자동 실행 금지)
- 예:
  - 일정 변경/약속 재조정
  - 서비스 범위 변경(견적 항목 변경/가격 조정 포함)
  - 특정 Agent로 변경

### 3) `REPLY_ONLY`
- 단순 안내/상태 응답/FAQ(버튼 없이 답변만)

> 참고: 현재 `services_quote_change_llm.py`의 intent 체계를 유지하되, 최상위 분류를 위 3개로 두고
> 기존 intent/action은 “하위 세부 intent/추천 액션”으로 매핑하는 방식을 권장합니다.

---

## Recommended action taxonomy (추천 액션 타입)
버튼/실행 대상은 “액션 타입”으로 표준화합니다.

### AUTO_CONFIRMABLE 액션(버튼 제공)
- **REOPEN_SURVEY**: 설문을 `REVISION_REQUESTED`로 전환(가능한 경우)
- **SEND_SURVEY_RESUME_LINK**: 설문 재개 링크 안내/재발송(실제로는 링크 제공이므로 실행은 “메시지 발송”에 해당)
- **RESEND_QUOTE**: 최근 `FINAL_SENT` 견적 재송부(이메일/앱 메시지)
- **OPEN_INBOX_CONVERSATION**: 해당 대화로 바로 이동(링크)

### HUMAN_REVIEW_REQUIRED 액션(버튼은 “검토 요청 접수” 수준)
- **CREATE_REVIEW_TICKET**(내부): Admin/Agent 큐에 태스크 생성(향후)
- **REQUEST_MORE_INFO**: 추가 질문 템플릿 자동 응답(버튼/폼)

### REPLY_ONLY 액션
- **SEND_FAQ_REPLY**: 상태/FAQ 자동 응답(버튼 없음)

---

## Execution mode taxonomy (실행 모드)
- **PROPOSE_ONLY**: 제안(버튼/안내)만 생성, 상태 변화 없음
- **CONFIRM_THEN_EXECUTE**: 고객 Confirm(버튼 클릭) 후 executor 실행
- **ADMIN_EXECUTE**: Admin이 검토 후 수동 실행(승인 버튼)

요구사항 7은 모든 AUTO_CONFIRMABLE에 대해 **CONFIRM_THEN_EXECUTE**를 강제합니다.

---

## 상태기계 분리(요구사항 10)
### A) SurveySubmission 상태기계(기존 유지)
- 편집 가능 상태는 `DRAFT`, `REVISION_REQUESTED`로 제한
- 서비스 진행 단계(`AGENT_ASSIGNMENT`, `SERVICE_IN_PROGRESS`)로 되돌리는 자동 전이는 금지

### B) QuoteChangeRequest 상태기계(기존 유지/정돈)
- “견적 수정 요청”의 처리 흐름을 추적
- 설문 재개 승인 시 `CUSTOMER_ACTION_REQUIRED`
- 고객 재제출 시 `IN_REVIEW`
- 새 견적 송부 시 `APPLIED`

### C) CustomerActionProposal 상태기계(신규)
고객에게 노출된 버튼의 생명주기를 추적합니다.

권장 상태:
- `PROPOSED`: 버튼 제안 생성(메시지로 안내 + 버튼 노출)
- `CONFIRMED`: 고객이 버튼 클릭(실행 요청)
- `EXECUTED`: 실행 성공
- `FAILED`: 실행 실패(재시도 가능)
- `EXPIRED`: 만료(시간 경과/상태 변화로 실행 불가)
- `CANCELED`: 더 이상 유효하지 않음(예: 이미 다른 경로로 처리됨)

---

## 정책 표(요구사항 5, “자동 가능 vs 사람 검토”)
아래 표는 “고객 메시지”를 받았을 때의 기본 분류/제안 액션 정책(초안)입니다.

| 고객 요청 예시 | LLM 상위분류 | 제안 버튼(액션) | 실행 주체 | 실행 전 조건(대표) | 실행 결과(대표) |
|---|---|---|---|---|---|
| 설문을 다시 수정하고 싶어요 / 이전 제출 내용을 바꾸고 싶어요 | AUTO_CONFIRMABLE | REOPEN_SURVEY | 고객 Confirm 후 시스템 | submission.status ∈ {SUBMITTED, AWAITING_PAYMENT} | submission → REVISION_REQUESTED, 안내 메시지 |
| 설문 링크 다시 주세요 | AUTO_CONFIRMABLE | SEND_SURVEY_RESUME_LINK | 고객 Confirm 후 시스템(=메시지 발송) | 로그인 가능/권한 OK | resume 링크 포함 자동 응답 |
| 견적서를 다시 보내주세요 | AUTO_CONFIRMABLE | RESEND_QUOTE | 고객 Confirm 후 시스템 | 존재하는 FINAL_SENT quote, not superseded? (정책) | 이메일/앱 메시지 재송부 |
| 일정 바꿔주세요 / agent와 약속 다시 | HUMAN_REVIEW_REQUIRED | (옵션) “요청 접수” 버튼 + 추가 질문 | 사람(Agent/Admin) | - | 담당자가 후속 처리 |
| 특정 agent로 바꿔주세요 | HUMAN_REVIEW_REQUIRED | REQUEST_MORE_INFO | 사람 | 결제/배정 상태 확인 필요 | 담당자 처리 |
| 가격 조정 부탁해요 / 서비스 범위 변경 | HUMAN_REVIEW_REQUIRED | (견적 수정 요청 폼) | 사람 | - | QuoteChangeRequest 생성 + Admin 검토 |
| 결제는 어떻게? / 진행상황 알려줘 | REPLY_ONLY | SEND_FAQ_REPLY | 시스템 | - | 자동 답변 |

---

## “메시지 → LLM → 제안 → 클릭 → 실행 → 상태 갱신” 목표 플로우
### 0) 컨텍스트 로딩
- conversation에서 연결된 `survey_submission` / 최신 quote / 최신 change_request / appointment 유무 등을 조회

### 1) 메시지 수신(고객)
- 메시지 저장(현재 `api_conversation_messages POST`)
- **즉시 상태 변경 금지**
- analyzer 호출(비동기 권장: celery/queue 없으면 동기 + 타임아웃/폴백)

### 2) LLM 분석
- 출력: 상위 분류(AUTO_CONFIRMABLE/HUMAN_REVIEW_REQUIRED/REPLY_ONLY) + 세부 intent + 추천 액션들
- 검증 실패 시: HUMAN_REVIEW_REQUIRED 또는 REPLY_ONLY로 폴백

### 3) Policy Engine 적용
- 현재 상태에서 실행 가능한 액션만 필터링
- 실행 불가하면 “대안 액션(링크 안내/관리자 검토)”로 degrade

### 4) CustomerActionProposal 생성
- 제안 메시지(자동 응답) + 버튼들을 proposal로 저장
- UI에서 proposal을 기반으로 버튼 렌더링(메시지함/견적/대시보드 공통)

### 5) 고객 버튼 클릭(Confirm)
- `POST /api/actions/<proposal_id>/confirm` (CSRF + 권한 검증)
- executor 실행 (idempotent)

### 6) 실행 후 상태 갱신/로그
- SurveySubmission/QuoteChangeRequest/Quote 상태 업데이트
- Proposal 상태 `EXECUTED`로 변경
- 결과 메시지(성공/실패) 자동 발송

---

## Admin initiated reopen(요구사항 8) 포함
Admin은 두 가지 모드를 가질 수 있습니다.
- **Admin-Execute**: 즉시 `REVISION_REQUESTED`로 전환 + 고객 안내 발송 (현행 `submission_review_request_revision`과 유사)
- **Admin-Propose**(권장): 고객에게 “설문 수정 시작” 버튼을 제안하고, 고객 클릭 시에만 전환  
  - 운영상 “고객이 실제로 수정할 의사가 있을 때만 상태를 바꾸고 싶다”면 이 모드를 택함

초기 단계에서는 기존 Admin-Execute를 유지하되, 내부적으로도 Policy Engine을 통해 “가능/불가”를 검증하도록 정리합니다.

---

## 상태 전이 표(핵심만)
### SurveySubmission
| From | Event | To | 제약 |
|---|---|---|---|
| SUBMITTED | 고객 Confirm: REOPEN_SURVEY | REVISION_REQUESTED | 서비스 진행 단계에서는 불가 |
| AWAITING_PAYMENT | 고객 Confirm: REOPEN_SURVEY | REVISION_REQUESTED | 결제 전이므로 가능(정책) |
| REVISION_REQUESTED | 고객 재제출 | SUBMITTED | 카드별 수정 요청 resolved 처리 |
| SUBMITTED | 견적 송부 | AWAITING_PAYMENT | quote FINAL_SENT |
| AWAITING_PAYMENT | 결제 | AGENT_ASSIGNMENT | quote PAID |

### CustomerActionProposal
| From | Event | To |
|---|---|---|
| PROPOSED | 고객 Confirm | CONFIRMED |
| CONFIRMED | 실행 성공 | EXECUTED |
| CONFIRMED | 실행 실패 | FAILED |
| PROPOSED | 상태 변화로 무효 | EXPIRED |
| * | 관리자 취소 | CANCELED |

---

## UI 반영 포인트(요구사항 6, 11)
### 공통 원칙
- UI는 “현재 상태를 직접 해석”하지 않고, **Policy Engine이 내려준 CTA 목록**을 표시한다.
- CTA는 “링크” 또는 “POST 실행” 두 종류로 통일한다.

### 메시지함(`templates/messaging/inbox.html`)
- 하단 액션 영역에 “proposal 기반 버튼”을 렌더링(여러 버튼 가능)
- 고객 메시지 전송 후 자동 응답(제안 메시지) + 버튼 표시

### 고객 대시보드(`templates/app/customer_dashboard.html`)
- 기존 `show_reopen_survey` 같은 단일 bool 대신 “proposal/cta 목록”을 표시
- (단계적 도입) 초기에는 기존 bool 유지 + policy 엔진 병행

### customer quote(`templates/services/customer_quote.html`)
- “견적서 수정 요청” 텍스트 입력은 유지하되,
  - 전송 시 LLM 결과에 따라 “버튼 제안”이 나타나고,
  - 설문 재개/견적 재송부 같은 실행은 버튼 Confirm 후에만 진행되도록 정리

---

## 구현 순서(권장)
1) **분석 결과/제안 저장 모델**(`CustomerActionProposal`) 추가 + 마이그레이션
2) **Policy Engine 모듈** 도입: “현재 상태 → 가능한 CTA”를 계산하는 순수 함수
3) 메시지 수신 경로에서
   - 휴리스틱 즉시 실행 제거(또는 feature flag로 비활성)
   - analyzer(LLM) 호출 → proposal 생성 → 자동 응답 메시지 발송
4) **Confirm API + Executor** 구현(최소: REOPEN_SURVEY, RESEND_QUOTE, SEND_SURVEY_RESUME_LINK)
5) UI 3곳(메시지함/대시보드/견적)에서 **policy 기반 CTA 렌더링**으로 통일
6) Admin 도구(리뷰 화면)도 policy/execute를 사용하도록 리팩터링
7) 로그/모니터링/재시도(FAILED/EXPIRED) 처리 추가

---

## 테스트 전략
### 단위 테스트
- Policy Engine: 상태 조합별 CTA 산출(스냅샷 테스트)
- Analyzer 출력 검증: 스키마/폴백
- Executor: idempotency(중복 Confirm), 상태 전이 불변식 검사

### 통합 테스트
- “메시지 → proposal 생성 → 버튼 Confirm → 실행 → CTA/상태 반영” E2E 시나리오
- 견적 송부 후(AWAITING_PAYMENT) 설문 재개, 기존 견적 superseded 처리

### 불변식(예)
- 서비스 진행 단계(`AGENT_ASSIGNMENT`, `SERVICE_IN_PROGRESS`)에서는 고객 메시지/버튼으로 설문을 `REVISION_REQUESTED`로 되돌리지 않는다.
- 가격 노출 정책: quote status < FINAL_SENT이면 메시지/응답에 금액 포함 금지.

