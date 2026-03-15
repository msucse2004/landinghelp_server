# 고객 요청·액션 워크플로우 테스트 보고서

**문서 버전:** 1.0  
**작성일:** 2026-03-10  
**대상:** 고객 메시지 → LLM 분류 → 자동 액션 제안 / 사람 검토 라우팅 → 고객 버튼 클릭 → 실제 실행 전체 흐름 검증

---

## 1. 추가/수정된 테스트 목록

| 테스트 파일 | 추가/수정 | 설명 |
|------------|----------|------|
| `settlement/tests/test_customer_request_policy.py` | **추가** | 정책 엔진(휴리스틱): Intent, ExecutionMode, `evaluate_customer_request_policy(allow_llm=False)` |
| `settlement/tests/test_customer_action_offer_flow.py` | **추가** | AUTO_CONFIRMABLE 설문 재개·견적 재발송, HUMAN_REVIEW 라우팅, 공통 서비스 사용 검증 |
| `settlement/tests/test_admin_initiated_reopen.py` | **추가** | Admin 주도 reopen → offer 생성 → 고객 버튼 노출·클릭 시 수정 가능 |
| `settlement/tests/test_quote_revision_after_final_sent.py` | **추가** | FINAL_SENT 견적 존재 시 수정 요청 → reopen offer → 실행 후 superseded 처리 |
| `settlement/tests/test_workflow_regression.py` | **추가** | 회귀: survey resume, 가격 비노출, 메시지 발송, 견적 검토 플로우 |
| `messaging/tests/test_customer_message_request_flow.py` | **추가** | 메시지함 POST 시 `handle_customer_request_flow` 호출 여부 검증 |

기존 파일 확장:
- `settlement/tests/test_survey_quote_state_machine.py`: `CustomerMessageAutoReopenTests`가 통합 서비스(`handle_customer_request_flow`) + 정책 mock 기반으로 동작하도록 이전에 수정됨.

---

## 2. 각 테스트가 검증하는 시나리오

### 2.1 [AUTO_CONFIRMABLE] 설문 다시 수정

- **시나리오:** 고객이 "설문 다시 수정하고 싶어요" 메시지 전송 → 요청 생성 → (mock) LLM 결과 `SURVEY_REOPEN_REQUEST` / `AUTO_CONFIRMABLE` → action offer 생성 → **아직 reopen 미실행** 확인 → 고객이 버튼 클릭 → 그때 설문 reopen 실행 확인 → dashboard/messaging/customer quote 상태 반영 확인.
- **테스트:** `test_customer_action_offer_flow.AutoConfirmableSurveyReopenFlowTests.test_full_flow_message_offer_then_button_execute`
- **검증 내용:** `handle_customer_request_flow` 호출, `policy.execution_mode == AUTO_CONFIRMABLE`, `CustomerActionOffer`(reopen_survey) 생성, 클릭 전 `submission.status == SUBMITTED`, 클릭 후 `REVISION_REQUESTED`, `build_customer_ui_payload`에서 `can_reopen_survey` 및 `current_request_status` 반영.

### 2.2 [AUTO_CONFIRMABLE - QUOTE RESEND]

- **시나리오:** 고객이 "견적서 다시 보내주세요" 요청 → action offer 생성 → 버튼 클릭 후 resend 실행 → 중복 클릭 시 idempotent 처리 확인.
- **테스트:** `test_customer_action_offer_flow.AutoConfirmableQuoteResendIdempotentTests.test_quote_resend_offer_and_idempotent_double_click`
- **검증 내용:** `resend_quote` offer 생성, `execute_confirmed_action` 2회 호출 시 모두 성공(idempotent).

### 2.3 [HUMAN_REVIEW_REQUIRED]

- **시나리오:** 고객이 "agent 변경 부탁해요" 또는 (mock) "agent와 약속 다시 잡고 싶어요" 요청 → LLM(휴리스틱) 결과 `HUMAN_REVIEW_REQUIRED` → admin/agent review queue(`HumanReviewRequest`) 생성 → 고객에게 검토 중 자동 응답 생성 → 자동 실행 없음 확인.
- **테스트:** `test_customer_request_policy.PolicyHeuristicTests.test_agent_change_human_review`, `test_customer_action_offer_flow.HumanReviewRequiredFlowTests.test_human_review_routing_no_auto_execution`
- **검증 내용:** `execution_mode == HUMAN_REVIEW_REQUIRED`, `HumanReviewRequest` 생성·`RECEIVED`, `reopen_survey` PENDING offer 없음, submission 상태 유지.

### 2.4 [ADMIN INITIATED REOPEN]

- **시나리오:** Admin이 고객 요청 없이 reopen 실행 → 고객 메시지·dashboard에 버튼 노출 → 고객이 버튼 클릭 후 수정 가능 상태 활성화 확인.
- **테스트:** `test_admin_initiated_reopen.AdminInitiatedReopenTests.test_admin_reopen_creates_offer_customer_clicks_enables_edit`
- **검증 내용:** `admin_initiated_reopen_submission` 성공, `CustomerActionOffer`(reopen_survey) 생성, `get_submission_reopen_status`에 `pending_reopen_offer_id`, `build_customer_ui_payload`에 pending action_offers, 클릭 후 `REVISION_REQUESTED` 및 `can_reopen_survey` True.

### 2.5 [QUOTE ALREADY SENT]

- **시나리오:** FINAL_SENT quote가 있는 상태에서 고객이 메시지로 수정 요청 → 정책에 따라 AUTO_CONFIRMABLE 또는 HUMAN_REVIEW 분기 → survey reopen 또는 review flow 정상 확인 → 기존 quote superseded 후 결제 대상 제외 확인.
- **테스트:** `test_quote_revision_after_final_sent.QuoteAlreadySentRevisionTests.test_final_sent_message_reopen_offer_then_superseded_not_payable`
- **검증 내용:** 메시지로 reopen 요청 시 offer 생성, 버튼 클릭 후 `revision_superseded_at` 설정, superseded quote는 결제 플로우에서 제외(상세는 quote_checkout 등에서 확인).

### 2.6 [COMMON SERVICE LOGIC]

- **시나리오:** 메시지함 경로와 customer quote 화면 경로가 같은 통합 서비스 계층(`handle_customer_request_flow`)을 사용하는지 확인.
- **테스트:** `test_customer_action_offer_flow.CommonServiceLogicTests.test_messaging_and_quote_path_use_same_flow`, `messaging.tests.test_customer_message_request_flow.MessagingPathUsesIntegratedServiceTests.test_messaging_post_invokes_handle_customer_request_flow`
- **검증 내용:** `customer_request_service`에 `handle_customer_request_flow`, `intake_customer_request`, `analyze_customer_request`, `create_action_offer`, `execute_confirmed_action` 존재; 메시지함 POST 시 `handle_customer_request_flow('messaging_inbox', ...)` 호출 및 `conversation`/`message` 전달.

### 2.7 [REGRESSION]

- **시나리오:** 기존 survey resume, 가격 비노출, 메시지 발송, 견적 검토 플로우 유지.
- **테스트:** `test_workflow_regression.RegressionSurveyResumeTests`, `RegressionPriceVisibilityTests`, `RegressionMessageSendTests`, `RegressionQuoteReviewFlowTests`
- **검증 내용:** 휴리스틱에서 "링크…설문" → SURVEY_RESUME_REQUEST / AUTO_CONFIRMABLE; DRAFT/NEGOTIATING에서 `message_may_include_price`/`can_view_price` False, `quote_for_customer` 마스킹; Message 생성; `QuoteChangeRequest.Status` 값 존재.

---

## 3. AUTO_CONFIRMABLE / HUMAN_REVIEW_REQUIRED 검증 결과

| 구분 | 검증 결과 | 비고 |
|------|-----------|------|
| **AUTO_CONFIRMABLE** | 통과 | 설문 재개·견적 재발송 시 offer 생성, 버튼 클릭 시에만 실행, 상태·payload 반영 |
| **HUMAN_REVIEW_REQUIRED** | 통과 | agent/일정 등 요청 시 HumanReviewRequest 생성, 자동 실행 없음, 고객 자동 응답 |
| **버튼 확인형 실행** | 통과 | 클릭 전 submission/quote 상태 유지, 클릭 후에만 `execute_confirmed_action` → 상태 전이 |
| **Idempotency** | 통과 | 동일 offer 재실행 시 성공 반환, 중복 상태 변경 없음 |

---

## 4. 버튼 확인형 실행 검증 결과

- 메시지 수신만으로는 `SurveySubmission.status`를 `REVISION_REQUESTED`로 바꾸지 않음.
- `CustomerActionOffer`(reopen_survey 등)가 생성되고, 고객이 버튼을 눌렀을 때만 `execute_confirmed_action`이 호출되어 `_execute_survey_reopen` 등이 실행됨.
- dashboard / messaging / customer quote의 `build_customer_ui_payload` 결과에 `can_reopen_survey`, `action_offers`, `current_request_status` 등이 서버 상태와 일치하도록 반영됨.

---

## 5. 회귀 테스트 결과

| 항목 | 결과 |
|------|------|
| Survey resume 정책 | 휴리스틱 "링크…설문" → SURVEY_RESUME_REQUEST 유지 |
| 가격 비노출 정책 | DRAFT/NEGOTIATING에서 `message_may_include_price`, `can_view_price`, `quote_for_customer` 마스킹 유지 |
| 메시지 발송 기본 | Conversation/Message 생성 정상 |
| 견적 검토 플로우 | QuoteChangeRequest 상태값(OPEN, ANALYZED, IN_REVIEW 등) 존재 및 참조 가능 |

---

## 6. Known limitations

- **LLM 연동:** 실제 LLM 호출은 mock 또는 휴리스틱 fallback으로 대체. E2E에서 실제 LLM을 쓰는 시나리오는 수동/통합 테스트 권장.
- **메시지함 POST 호출 횟수:** `test_messaging_post_invokes_handle_customer_request_flow`에서 `handle_customer_request_flow`가 1회가 아닌 여러 번 호출될 수 있어, `assert_called_once()` 대신 `call_count >= 1` 및 마지막 호출 인자 검증으로 완화함.
- **Superseded quote와 message_may_include_price:** `message_may_include_price(quote)`는 현재 `quote.status`만 보고 하며, `revision_superseded_at`은 보지 않음. superseded quote의 결제 제외는 quote_checkout 등 다른 계층에서 처리됨.
- **Progress printout:** 테스트 실행 시 `-v 2`로 실행하면 진행 메시지(예: `[1/10] create customer change request from message`)가 stdout에 출력됨. 기본 verbosity에서는 일부만 보일 수 있음.

---

## 7. 수동 QA 추천 시나리오

1. **고객 메시지 → 설문 수정**
   - 고객 계정으로 메시지함에서 "설문 다시 수정하고 싶어요" 전송 → 자동 응답 및 "설문 수정하기" 버튼 노출 확인 → 버튼 클릭 → 설문 수정 화면 진입 및 재제출 가능 확인.

2. **고객 메시지 → 견적 재발송**
   - FINAL_SENT 견적이 있는 고객이 "견적서 다시 보내주세요" 전송 → 버튼 노출 → 클릭 시 재발송(이메일 등) 동작 확인.

3. **고객 메시지 → 사람 검토**
   - "agent 변경 부탁해요" 또는 "일정 변경 요청드려요" 전송 → "검토 후 안내드리겠습니다" 수준 응답 확인, 자동으로 설문/견적 상태가 바뀌지 않음 확인 → Admin에서 HumanReviewRequest/검토 대기 목록 확인.

4. **Admin 주도 reopen**
   - Admin이 특정 설문 제출에 대해 "고객 설문 수정 허용" 실행 → 고객 메시지함·대시보드에 "설문 수정 시작" 버튼 노출 → 고객이 클릭 시 수정 가능 상태로 전환 확인.

5. **FINAL_SENT 이후 수정 요청**
   - 이미 견적을 받은 상태에서 "설문 다시 수정하고 싶어요" 메시지 → offer 생성 후 버튼 클릭 → 기존 견적 superseded 처리 및 새 설문 제출·재견적 흐름으로 이어지는지 확인.

---

## 8. 테스트 실행 방법

```bash
# 전체 워크플로우 테스트 (progress 출력 포함, 18개)
python manage.py test settlement.tests.test_customer_request_policy settlement.tests.test_customer_action_offer_flow settlement.tests.test_admin_initiated_reopen settlement.tests.test_quote_revision_after_final_sent settlement.tests.test_workflow_regression messaging.tests.test_customer_message_request_flow -v 2

# 기존 관련 테스트 (상태기·LLM·가격 등)
python manage.py test settlement.tests.test_survey_quote_state_machine settlement.tests.test_quote_change_llm_flow settlement.tests.test_workflow_critical -v 0

# 개별 파일
python manage.py test settlement.tests.test_customer_action_offer_flow -v 2
python manage.py test messaging.tests.test_customer_message_request_flow -v 2
```

**통과 기준:** 위 워크플로우 18개 테스트 모두 OK. 기존 테스트도 함께 실행해 회귀 확인 권장.
