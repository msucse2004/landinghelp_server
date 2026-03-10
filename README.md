# landinghelp_server

Django 백엔드 (설문·견적·메시지·고객 요청 자동 분류·제안 플로우).  
다른 챗봇/개발 환경에서 이어서 개발할 때 이 문서를 기준으로 현재 구현 상태를 파악할 수 있습니다.

---

## 1. 프로젝트 개요

- **프레임워크**: Django (Python 3)
- **DB**: PostgreSQL
- **주요 기능**: 설문(Survey), 견적(Quote), 결제/플랜(Billing), 메시지함(Messaging), 고객 텍스트 요청 분류(휴리스틱 → Ollama → Gemini), 제안(Proposal) 기반 액션 실행, 학습 신호(FeedbackLog) 수집

---

## 2. 현재 구현 상태 (고객 요청 → 제안 → 실행)

### 2.1 전체 흐름

1. **고객이 텍스트 메시지 전송** (메시지함 또는 견적 수정 요청)
2. **진입**  
   - 메시지함: `handle_customer_request_flow(channel="messaging_inbox", ..., conversation=, message=)`  
   - 견적 수정: `handle_customer_request_flow(channel="customer_quote_revision", ..., quote=)`
3. **분류**  
   - `customer_request_policy.classify_customer_request(text)`  
   - 순서: **Heuristic → Ollama → Gemini** (confidence/risk에 따라 단계 스킵 가능)
4. **분류 결과 저장**  
   - `CustomerRequestIntentAnalysis` 1건 생성 (원문, intent, action, confidence, source 등)
5. **라우팅**  
   - **LOW risk (AUTO_CONFIRMABLE)**: `CustomerActionProposal` 생성 → 고객에게 “제안 메시지 + 확인/취소 버튼” 표시. **즉시 실행 없음.**  
   - **HIGH risk**: Human review 경로 (`HumanReviewRequest` 등).  
   - **REPLY_ONLY**: 자동 응답만.
6. **고객이 버튼 클릭**  
   - **확인**: `POST /api/settlement/proposal/<id>/confirm/` → `confirm_proposal()` → 상태 PROPOSED → CONFIRMED → 액션 실행 → EXECUTED/FAILED, 고객 대화에 성공/실패 메시지 전송  
   - **취소**: `POST /api/settlement/proposal/<id>/decline/` → `decline_proposal()` → DECLINED, 액션 미실행  
   - **레거시 오퍼**: `POST /api/settlement/action-offer/<id>/execute/` (CustomerActionOffer용)
7. **학습 신호**  
   - `CustomerActionFeedbackLog`: USER_CONFIRMED, USER_DECLINED, ACTION_STARTED, ACTION_SUCCEEDED, ACTION_FAILED, USER_CORRECTED, FOLLOWUP_SUCCESS 등 + structured payload (predicted_intent, user_feedback, final_outcome 등). 향후 ML/retrieval export용.

### 2.2 정책 테이블 (안전한 자동 제안)

- **파일**: `customer_request_policy.py`
- **구성**: `_POLICY_ENTRIES` (ActionPolicyEntry 튜플) → `INTENT_POLICY`, `ACTION_CODE_POLICY` 인덱스
- **항목 필드**: intent, risk_level(LOW/HIGH/INFO), requires_user_confirmation, allows_direct_execution, requires_human_review, execution_mode, human_review_target, recommended_action, action_code, proposal_type, proposal_template_key, button_label, offer_title, guide_message, success_message, customer_facing_summary

**LOW risk (확인 후 실행)**  
- SURVEY_REOPEN_REQUEST → reopen_survey  
- SURVEY_RESUME_REQUEST → resume_survey  
- QUOTE_RESEND_REQUEST → resend_quote  
- PAYMENT_LINK_RESEND_REQUEST → resend_payment_link  

**HIGH risk (human review)**  
- QUOTE_ITEM_CHANGE_REQUEST, SCHEDULE_CHANGE_REQUEST, AGENT_CHANGE_REQUEST, PRICING_NEGOTIATION_REQUEST, REFUND_REQUEST, LEGAL_COMPLAINT  

**INFO (응답만)**  
- STATUS_CHECK, GENERAL_QUESTION, UNSUPPORTED_REQUEST  

**새 intent/action 추가 시**  
1. `Intent` / `RecommendedAction` enum에 값 추가  
2. `_POLICY_ENTRIES`에 `ActionPolicyEntry` 한 항목 추가  
3. (auto-confirmable이면) `customer_request_service._get_action_executors()`에 action_code → 실행 함수 등록  
4. (휴리스틱 매칭 필요 시) `_HEURISTIC_PATTERNS`에 (regex, intent, confidence, summary_override, reasoning) 추가  

나머지(버튼 문구, 안내/성공 메시지, 리스크 판정, LLM 강등 등)는 정책 테이블에서 자동 반영됩니다.

### 2.3 핵심 모델 (messaging)

| 모델 | 용도 |
|------|------|
| **CustomerRequestIntentAnalysis** | 메시지별 분류 결과 1건. customer, conversation, message, original_text, predicted_intent, predicted_action, execution_mode, confidence, source, raw_model_output, target_section_ids |
| **CustomerActionProposal** | 제안 1건. analysis FK, proposal_type, title, body, action_code, action_payload(JSON), status(PROPOSED/CONFIRMED/DECLINED/EXPIRED/EXECUTED/FAILED), submission, quote, conversation, expires_at, confirmed_at, declined_at, executed_at, failure_reason |
| **CustomerActionFeedbackLog** | 제안별 이벤트 로그(append-only). proposal FK, event_type(PROPOSAL_SHOWN, USER_CONFIRMED, USER_DECLINED, ACTION_STARTED, ACTION_SUCCEEDED, ACTION_FAILED, USER_CORRECTED, FOLLOWUP_SUCCESS, PROPOSAL_EXPIRED, ADMIN_OVERRIDE), event_payload(JSON, 학습 신호용), actor |

### 2.4 API 엔드포인트 (고객 요청/제안 관련)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/settlement/proposal/<id>/confirm/` | 제안 확인 → 액션 실행, JSON `{ ok, message? }` |
| POST | `/api/settlement/proposal/<id>/decline/` | 제안 거절 → DECLINED, 액션 미실행 |
| POST | `/api/settlement/proposal/<id>/shown/` | 제안 카드 노출 시 PROPOSAL_VIEWED 로그 (중복 호출 허용) |
| POST | `/api/settlement/action-offer/<id>/execute/` | 레거시 CustomerActionOffer 실행. AJAX면 JSON, 폼 제출이면 성공 시 설문 편집 페이지로 302 |

### 2.5 주요 파일 위치

| 역할 | 파일 |
|------|------|
| 정책·분류·휴리스틱 | `customer_request_policy.py` (프로젝트 루트) |
| 통합 서비스·제안 생성·확인/거절·실행·학습신호 | `customer_request_service.py` (프로젝트 루트) |
| LLM 호출·검증·강등 | `customer_request_llm.py` (프로젝트 루트) |
| Intent/Proposal/FeedbackLog 모델 | `messaging/models.py` |
| 제안 확인/거절/shown 뷰 | `settlement/views.py` (api_proposal_confirm, api_proposal_decline, api_proposal_mark_shown) |
| 메시지함 API·payload·action_offers | `messaging/views.py` |
| 메시지함 UI·제안/오퍼 카드·버튼 | `templates/messaging/inbox.html` |
| 설문 제출·재제출 시 FOLLOWUP_SUCCESS | `survey/views.py` (survey_submit 내 record_followup_success 호출) |

### 2.6 설문 수정 흐름 (참고)

- **고객이 메시지로 “설문 수정 요청”**  
  시스템 자동 응답 + 「설문 수정하기」 버튼(Proposal). 고객이 **버튼 클릭 시** 그때 submission → REVISION_REQUESTED 전환 후 설문 편집 페이지로 이동. (Admin 메시지 없음.)
- **Admin이 설문 재개 승인**  
  Admin 승인 시 즉시 REVISION_REQUESTED. 고객에게 “설문 수정 허용” 메시지 발송. 고객은 별도 수락 없이 「설문 수정하기」만 누르면 편집 페이지로 이동.

---

## 3. 환경 및 실행

### 3.1 환경 변수 (.env)

- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`
- DB: `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- 이메일: `EMAIL_*` (실제 발송 시 환경변수 권장)
- `DEEPL_AUTH_KEY`: 번역
- `OLLAMA_URL`, `OLLAMA_MODEL`: Ollama (분류/번역)
- Gemini: `customer_request_llm`/`ai_agent`에서 사용하는 API 키는 해당 모듈 또는 `.env` 참조

`.env.example`을 복사해 `.env` 생성 후 값을 채우면 됩니다.

### 3.2 DB·마이그레이션·실행

```bash
# 가상환경 활성화 후
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser   # 필요 시
python manage.py runserver
```

Docker 사용 시:

```bash
docker compose up -d
docker compose exec web python manage.py migrate
```

### 3.3 테스트

```bash
# 고객 요청·제안·정책 테이블·피드백 로그 통합 테스트 (34개)
python manage.py test messaging.tests.test_proposal_flow --verbosity=2

# 견적 수정·LLM·설문 재개 관련 (21개)
python manage.py test settlement.tests.test_quote_change_llm_flow --verbosity=2

# 위 두 개 동시 실행 (55개)
python manage.py test messaging.tests.test_proposal_flow settlement.tests.test_quote_change_llm_flow --verbosity=2
```

---

## 4. 앱 구성 (INSTALLED_APPS)

- accounts, billing, content, settlement, survey, community, messaging, translations, ai_agent, adminsortable2

---

## 5. URL 구조 (일부)

- `/` : 홈  
- `/app/` : 앱 진입 (role별 대시보드)  
- `/messages/` : 메시지함  
- `/api/messaging/` : 메시지 API  
- `/settlement/survey/` : 설문  
- `/api/settlement/proposal/<id>/confirm|decline|shown/` : 제안 확인/거절/노출 로그  
- `/api/settlement/action-offer/<id>/execute/` : 레거시 오퍼 실행  
- `/admin/review/<submission_id>/` : 제출 검토 (Admin)  
- `/admin/review/<submission_id>/change-request/<cr_id>/approve-reopen-survey/` : 설문 재개 승인  
- `/admin/review/<submission_id>/reopen-survey/` : Admin이 설문 수정 허용 (즉시 REVISION_REQUESTED + 고객 메시지)

---

## 6. 문서 (docs/)

- `docs/WORKFLOW_AND_INTEGRATION.md` : 설문·견적·결제·스케줄·AI 어시스턴트·후기 플로우, 상태 전이, 스케줄링  
- `docs/SCHEDULING.md` : 스케줄 작업(설문 리마인드 등)  
- `docs/quote-change-request-llm-plan.md`, `docs/customer_request_action_workflow_plan.md` : 견적 수정·고객 요청 액션 설계  
- 기타 번역/검증/플로우 검토 문서 다수

---

## 7. 남은 리스크·확장 시 유의점

- **LLM 프롬프트**: Ollama/Gemini 분류 프롬프트에 새 Intent(REFUND_REQUEST, LEGAL_COMPLAINT 등)가 명시되어 있지 않을 수 있음. 정책 테이블은 대응하므로, 분류 정확도를 위해 프롬프트에 intent 목록 반영 권장.
- **ProposalType**: `CustomerActionProposal.ProposalType`에 PAYMENT_LINK_RESEND 등이 choices로 들어가 있음. 새 제안 유형 추가 시 choices와 정책 테이블 proposal_type 일치 여부 확인.
- **정정 감지**: “그게 아니라” 등 USER_CORRECTED는 휴리스틱 정규식 기반. 오탐 가능성 있음. 필요 시 LLM 기반 정정 분류로 확장 가능.
- **레거시 CustomerActionOffer**: 신규 플로우는 CustomerActionProposal. CustomerActionOffer는 견적/대시보드 등에서 여전히 사용 가능. 두 체계가 병존하므로 프론트/백엔드에서 proposal_id 유무로 구분해 처리함.

---

## 8. 다른 챗봇에서 이어받을 때 체크리스트

1. **정책 추가**  
   - `customer_request_policy.py`의 `Intent`/`RecommendedAction` 및 `_POLICY_ENTRIES`, `_HEURISTIC_PATTERNS`  
   - 실행이 필요하면 `customer_request_service._get_action_executors()`에 등록  
2. **분류/실행 흐름**  
   - 진입: `handle_customer_request_flow` (호출처: 메시지 저장 후 또는 견적 수정 요청 시)  
   - 확인/거절: `confirm_proposal`, `decline_proposal`  
3. **UI**  
   - 메시지함: `templates/messaging/inbox.html`의 `renderActionCards`, proposal_id 있으면 확인/취소 버튼, 없으면 레거시 오퍼 execute  
   - 견적/대시보드: `action-offer/<id>/execute/` 호출 시 `X-Requested-With: XMLHttpRequest` 있으면 JSON, 없으면 성공 시 설문 편집 페이지로 302  
4. **테스트**  
   - `messaging.tests.test_proposal_flow`  
   - `settlement.tests.test_quote_change_llm_flow`  
5. **학습 신호**  
   - `CustomerActionFeedbackLog`의 event_payload 구조 유지 시 향후 ML/retrieval export에 그대로 사용 가능.

이 문서와 `customer_request_policy.py`, `customer_request_service.py` 주석/독스트링을 함께 보면 현재 구현 상태를 이어받기 좋습니다.
