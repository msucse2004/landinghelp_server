# 견적 수정 요청 LLM 확장 설계 (UCD 관점)

**문서 버전:** 1.0  
**대상:** Django 프로젝트 — 견적 수정 요청(quote change request) 기능의 LLM 기반 의도 분류·액션 추천·워크플로우 연동  
**목적:** 코드 수정 없이 설계 문서만 작성. 실무 설계 문서 형식.

---

## 1. 현재 customer_quote의 자유 텍스트 수정 요청 방식 한계

### 1.1 현행 구현 요약

- **진입점:** 고객이 `FINAL_SENT` 견적을 받은 후 `templates/services/customer_quote.html`의 "견적서 수정 요청" 영역에서 **자유 텍스트**만 입력하여 전송.
- **API:** `settlement/views.py` — `api_quote_request_revision(request)`  
  - POST JSON: `{ "quote_id": int, "message": str }`.
  - 동작: 해당 `SettlementQuote`의 `status`를 `NEGOTIATING`으로 변경하고, 설문 제출과 연결된 공유 대화(Conversation)에 고객 메시지로 `"견적서 수정 요청\n\n" + message`를 추가. Admin은 메시지함에서 확인 후 수동으로 검토·수정·재송부.

### 1.2 한계

| 한계 | 설명 |
|------|------|
| **구조화 부재** | 요청이 순수 텍스트라 "서비스 추가/제거/금액 변경/설문 재작성/일반 문의" 등 **의도가 코드/데이터로 구분되지 않음**. |
| **Admin 수동 해석** | Admin이 매번 메시지를 읽고 의도를 추론한 뒤, 설문 재개 vs 견적 수정 등 **다음 액션을 직접 결정**해야 함. |
| **워크플로우 미연결** | 설문 재수정(REVISION_REQUESTED) 플로우와 견적 수정(draft 생성·가격 수정·재송부) 플로우가 **같은 요청에서 자동으로 분기·연결되지 않음**. |
| **고객 피드백 부족** | 고객은 "요청이 접수되었습니다" 수준의 안내만 받고, **어떤 다음 단계(설문 수정 링크 vs 수정 견적 대기 등)가 기대되는지** 명시적 안내가 없음. |
| **이력/감사 부족** | 요청별로 "의도 분류 결과·추천 액션·Admin이 선택한 액션"이 **영구 저장되지 않아** 감사·분석·재현이 어렵다. |

---

## 2. UCD 관점 Pain Point

### 2.1 고객(사용자)

- 요청 제출 후 **다음에 무엇을 해야 하는지**(설문 수정으로 가야 하는지, 견적만 기다리면 되는지) 불명확.
- "일정/인원 변경은 설문 수정으로 해주세요" 같은 **컨텍스트에 맞는 유도**가 없음.

### 2.2 Admin(관리자)

- 자유 텍스트를 **매번 수동 해석**해야 하며, 요청이 견적 항목 변경인지 설문 재작성인지 문의인지 구분하는 데 시간이 듦.
- 설문 재개와 견적 수정이 **별도 화면/플로우**라, 한 요청에 대해 "설문 먼저 열고 → 수정 후 제출 → 그 다음 견적 재작성" 같은 **순서가 자동으로 제안되지 않음**.

### 2.3 시스템/운영

- **설문 재수정**과 **견적 재작성** 흐름이 한 요청과 **논리적으로 연결되지 않음**. 같은 고객 메시지에 대해 설문 상태 변경(REVISION_REQUESTED) 또는 견적 draft 생성이 트리거되는 **일관된 규칙**이 없음.

---

## 3. 새 워크플로우 제안

```
[고객] 자유 텍스트 수정 요청 전송
        ↓
[시스템] 공유 대화에 고객 메시지 저장 (기존과 동일)
        ↓
[시스템] QuoteChangeRequest 레코드 생성 (quote, message, status=PENDING_ANALYSIS)
        ↓
[비동기/동기] LLM Intent Interpretation
        - 입력: message, quote context(항목 요약, submission 상태)
        - 출력: intent taxonomy, confidence, 추천 action list
        ↓
[시스템] QuoteChangeAnalysis 저장 (intent, confidence, recommended_actions[])
        ↓
[Admin] 메시지함/검토 화면에서
        - 고객 메시지 + LLM 해석 결과 + 추천 액션 확인
        - "설문 재개" / "견적 수정(초안 생성)" / "문의만 답장" / "수동 검토" 중 선택
        ↓
[시스템] Admin 확인에 따라:
        A) 설문 재개 → SurveySubmission.status = REVISION_REQUESTED, 고객에게 설문 수정 링크 전달
        B) 견적 수정 → 기존 draft 또는 sent quote 기반 새 DRAFT 생성, Admin이 가격/항목 수정 후 재송부
        C) 문의만 답장 → 기존 대화에 Admin 답장만 추가
        D) 수동 검토 → 상태만 "수동 검토 중" 등으로 남기고, 이후 Admin이 수동으로 A/B/C 수행
        ↓
[시스템] QuoteChangeActionLog 기록 (admin 선택 액션, 실행 결과)
```

- **LLM 단독으로 상태 변경 금지:** intent/추천은 "제안"만 하며, 실제 상태 변경(설문 재개, 견적 생성/송부)은 **Admin 승인 후** 실행.

---

## 4. LLM Safety 원칙

| 원칙 | 내용 |
|------|------|
| **No autonomous state change** | LLM 출력만으로 `SurveySubmission.status`, `SettlementQuote` 생성/삭제/status 변경, 메시지 자동 발송 등을 수행하지 않는다. |
| **Destructive action = admin only** | 서비스 제거, 견적 무효화, 설문 초기화 등 **destructive** 또는 **비가역에 가까운** 액션은 반드시 Admin 확인 후 실행. |
| **Confidence threshold** | intent/액션별 confidence가 설정값(예: 0.8) 미만이면 `URGENT_ADMIN_REVIEW` 또는 `PROPOSE_MANUAL_REVIEW`로 올리고, 자동 추천만 제공. |
| **Fallback** | LLM 호출 실패/타임아웃 시: 요청은 `PENDING_ANALYSIS` 또는 `MANUAL_REVIEW`로 두고, Admin에게 "분류 실패, 수동 검토 필요"로 표시. |
| **Audit** | 모든 LLM 입력/출력·추천 액션·Admin 선택·실행 결과를 `QuoteChangeRequest` / `QuoteChangeAnalysis` / `QuoteChangeActionLog`에 저장해 추적 가능하게 함. |

---

## 5. 새 도메인 모델 제안

### 5.1 QuoteChangeRequest

| 필드 | 타입 | 설명 |
|------|------|------|
| id | PK | |
| quote | FK(SettlementQuote) | 대상 견적 |
| submission | FK(SurveySubmission) | quote.submission (편의/쿼리용) |
| user | FK(User) | 요청한 고객 |
| message | TextField | 고객이 입력한 자유 텍스트 |
| status | CharField | PENDING_ANALYSIS, ANALYZED, AWAITING_ADMIN, IN_PROGRESS, RESOLVED, CANCELLED |
| message_link | FK(Message), null | 공유 대화에 저장된 메시지 (선택, 감사용) |
| created_at, updated_at | DateTimeField | |

- 한 견적에 대해 여러 번 수정 요청 가능(이력).

### 5.2 QuoteChangeRequestItem (선택)

- **용도:** 요청을 "항목 단위"로 쪼갤 경우(예: LLM이 "A 서비스 추가, B 서비스 제거"로 파싱한 경우).
| 필드 | 타입 | 설명 |
|------|------|------|
| id | PK | |
| change_request | FK(QuoteChangeRequest) | |
| action_type | CharField | ADD / REMOVE / CHANGE 등 (action taxonomy와 매핑) |
| service_code | CharField, null | 대상 서비스 코드 |
| payload | JSONField | 금액 변경 시 new_price 등 |
| sort_order | PositiveIntegerField | |

- 초기에는 생략하고, intent + recommended_actions만 저장해도 됨. 필요 시 Phase 2에서 추가.

### 5.3 QuoteChangeAnalysis

| 필드 | 타입 | 설명 |
|------|------|------|
| id | PK | |
| change_request | OneToOne(QuoteChangeRequest) | |
| intent | CharField | intent taxonomy (QUOTE_ITEM_CHANGE_REQUEST 등) |
| confidence | FloatField | 0.0~1.0 |
| raw_llm_response | JSONField, null | LLM 원문 (디버깅/감사) |
| recommended_actions | JSONField | [{ "action": "PROPOSE_ADD_SERVICE", "params": {...}, "confidence": 0.9 }, ...] |
| analyzed_at | DateTimeField | |
| model_version | CharField, null | LLM 모델/버전 식별자 |

### 5.4 QuoteChangeActionLog

| 필드 | 타입 | 설명 |
|------|------|------|
| id | PK | |
| change_request | FK(QuoteChangeRequest) | |
| performed_by | FK(User) | Admin |
| action | CharField | 실제 수행한 액션 (PROPOSE_REOPEN_SURVEY 등) |
| outcome | CharField | SUCCESS, FAILURE, PARTIAL |
| details | JSONField, null | 생성된 draft_id, submission_id 등 |
| created_at | DateTimeField | |

- Admin이 "설문 재개"를 선택해 실행한 경우, 여기에 `action=PROPOSE_REOPEN_SURVEY`, `outcome=SUCCESS`, `details={ "submission_id": ... }` 형태로 기록.

---

## 6. 추천 Intent Taxonomy

| Intent | 설명 | 예시 메시지 |
|--------|------|-------------|
| **QUOTE_ITEM_CHANGE_REQUEST** | 견적 항목 추가/제거/변경(금액·수량 등) 요청 | "OO 서비스 추가해 주세요", "은행 계좌 개설 금액만 조정 부탁드립니다" |
| **SURVEY_REOPEN_REQUEST** | 설문 내용(일정, 인원, 지역 등) 수정을 위한 설문 재작성 요청 | "입국일이 바뀌었어요", "인원 수 수정하고 싶습니다" |
| **GENERAL_QUESTION** | 견적/결제/일정에 대한 단순 문의. 항목 변경·설문 재작성 아님 | "결제는 언제까지 하면 되나요?", "서비스 날짜만 문의드립니다" |
| **UNSUPPORTED_REQUEST** | 시스템이 처리할 수 없는 요청(취소 요청, 환불, 법적 요청 등) | "견적 취소해 주세요", "환불 부탁드립니다" |
| **URGENT_ADMIN_REVIEW** | LLM이 의도를 낮은 신뢰도로만 추론했거나, 위험/민감 내용이 감지된 경우. Admin 수동 검토 유도 | (confidence < threshold 또는 키워드 기반 플래그) |

---

## 7. 추천 Action Taxonomy

| Action | 설명 | 실행 시 기대 동작 (Admin 승인 후) |
|--------|------|-----------------------------------|
| **PROPOSE_ADD_SERVICE** | 특정 서비스 추가 제안 | 견적 draft에 해당 서비스 라인 추가 (Admin이 가격 입력) |
| **PROPOSE_REMOVE_SERVICE** | 특정 서비스 제거 제안 | 견적 draft에서 해당 항목 제거 |
| **PROPOSE_CHANGE_SERVICE** | 기존 서비스 금액/수량/옵션 변경 제안 | draft에서 해당 항목만 수정 |
| **PROPOSE_REOPEN_SURVEY** | 설문 재개 제안 | SurveySubmission.status = REVISION_REQUESTED, 고객에게 설문 수정 링크 전달 |
| **PROPOSE_ADMIN_REPLY_ONLY** | 문의에 대한 답장만 필요 | Admin이 대화에 답장; 견적/설문 상태 변경 없음 |
| **PROPOSE_MANUAL_REVIEW** | 자동 추천 불가, Admin이 직접 판단 | 상태를 "수동 검토 중"으로 두고, Admin이 나중에 위 액션 중 하나를 선택해 실행 |

---

## 8. 설문 재개 UX

- **기존 답변 유지:** 설문 재개 시 기존 `SurveySubmission.answers`를 유지한 채 수정만 가능하도록. 고객은 변경하고 싶은 카드/문항만 수정.
- **진입 경로:**
  - **메시지 링크:** Admin이 "설문 수정이 필요합니다" 액션을 실행하면, 고객에게 보내는 메시지(또는 기존 공지 대화)에 **설문 수정 URL** 포함. 예: `/settlement/survey/?submission_id=...` 또는 서명된 토큰 링크.
  - **대시보드:** 고객 대시보드에서도 "설문 수정이 요청되었습니다" 배너/카드 노출 후, 동일한 설문 수정 URL로 진입.
- **일관성:** 메시지함에서 받은 링크로 진입하든, 대시보드에서 진입하든 **같은 설문(같은 submission)**에 대해 동일한 폼·진행 상태가 보이도록 함.

---

## 9. 견적 이력 정책

- **Hard delete 금지:** 이미 고객에게 송부된 `FINAL_SENT` 또는 `PAID` 견적은 **물리 삭제하지 않음**. 감사·분쟁·환불 처리 시 필요.
- **버전/상태 표현 제안:**
  - **superseded:** 이 견적이 이후 다른 견적(수정본)으로 대체됨. `superseded_by` FK로 새 견적 참조.
  - **revision_requested:** 고객이 수정 요청함 (현재 `NEGOTIATING`과 유사). 추후 `QuoteChangeRequest`와 연결해 "어떤 요청에 의해 revision_requested가 되었는지" 추적 가능.
  - **inactive:** 더 이상 고객에게 "현재 유효한 견적"으로 노출하지 않음. 이력 조회·Admin 목록에서는 필터로만 사용.
- **신규 견적 생성 규칙:** Admin이 "견적 수정" 플로우로 새 버전을 만들 때는 **새 SettlementQuote**를 생성하고, 필요 시 이전 quote에 `superseded_by=new_quote` 설정. 기존 quote는 `FINAL_SENT` 또는 `inactive`로 유지.

---

## 10. 단계별 구현 TODO

| Phase | 내용 | 우선순위 |
|-------|------|----------|
| **1. 모델 & API 기반** | QuoteChangeRequest, QuoteChangeAnalysis, QuoteChangeActionLog 모델 추가 및 마이그레이션. `api_quote_request_revision`에서 QuoteChangeRequest 생성 및 status=PENDING_ANALYSIS 저장. Admin 검토 목록 API(또는 기존 submission_review 확장). | P0 |
| **2. LLM 연동** | Intent interpretation 서비스 구현 (입력: message + quote/submission 요약, 출력: intent + confidence + recommended_actions). QuoteChangeAnalysis 저장. 실패 시 MANUAL_REVIEW. | P0 |
| **3. Admin UI** | 메시지함/검토 화면에서 "수정 요청" 클릭 시 고객 메시지 + LLM 해석 + 추천 액션 표시. "설문 재개" / "견적 수정" / "답장만" / "수동 검토" 버튼 및 확인 플로우. | P0 |
| **4. 액션 실행** | Admin 선택에 따른 실행: (A) 설문 재개 → REVISION_REQUESTED + 고객 메시지/이메일에 설문 링크. (B) 견적 수정 → create_draft_from_sent 호출 또는 유사 로직 + Admin을 견적 편집 화면으로 유도. (C) 답장만. (D) 상태만 변경. QuoteChangeActionLog 기록. | P0 |
| **5. 고객 안내** | 요청 접수 시/분류 후 고객에게 "요청이 분류되었습니다. Admin 검토 후 설문 수정 링크 또는 수정 견적을 보내드립니다" 등 문구. 설문 재개 시 메시지/이메일 본문에 설문 수정 URL 포함. | P1 |
| **6. 견적 이력** | SettlementQuote에 superseded_by, inactive 플래그(또는 status 확장) 및 마이그레이션. Admin에서 "이전 견적" 목록/링크 표시. | P1 |
| **7. QuoteChangeRequestItem** | 항목 단위 파싱(ADD/REMOVE/CHANGE)이 필요하면 LLM 출력을 RequestItem으로 저장하고, Admin UI에서 항목별로 수락/수정 가능하게. | P2 |
| **8. Confidence & 안전** | confidence threshold 설정, URGENT_ADMIN_REVIEW 자동 할당, LLM 입력/출력 sanitization 및 로그 제한(개인정보 최소화). | P1 |

---

## 11. 테스트 포인트

- **단위:** Intent interpretation 함수: 다양한 message에 대해 기대한 intent/actions 반환하는지. confidence < threshold일 때 URGENT_ADMIN_REVIEW 또는 PROPOSE_MANUAL_REVIEW 반환하는지.
- **단위:** QuoteChangeRequest 생성: `api_quote_request_revision` 호출 시 QuoteChangeRequest가 생성되고, 공유 대화에 메시지가 추가되는지. quote.status가 NEGOTIATING으로 변경되는지.
- **통합:** Admin이 "설문 재개" 선택 → submission.status = REVISION_REQUESTED, 고객 대상 메시지/이메일에 설문 링크 포함되는지.
- **통합:** Admin이 "견적 수정" 선택 → 새 DRAFT 생성(또는 기존 create_draft_from_sent 플로우) 후 해당 견적 편집 페이지로 리다이렉트되는지. QuoteChangeActionLog에 기록되는지.
- **E2E:** 고객이 수정 요청 → Admin이 로그인 후 요청 목록에서 확인 → LLM 해석 및 추천 액션 확인 → "설문 재개" 실행 → 고객이 메시지/대시보드에서 설문 수정 링크 클릭 → 동일 설문 폼이 열리는지.
- **안전:** LLM 응답을 그대로 상태 변경에 사용하지 않고, 항상 Admin 확인 후에만 상태 변경이 일어나는지 검증.

---

## 12. 리스크와 Fallback 전략

| 리스크 | 완화/ Fallback |
|--------|-----------------|
| **LLM 오분류** | confidence threshold 미만이면 전부 MANUAL_REVIEW. Admin이 추천을 수정하거나 무시하고 직접 액션 선택 가능. |
| **LLM 장애/지연** | 타임아웃(예: 10초) 후 분석 실패로 처리하고, status=PENDING_ANALYSIS 또는 MANUAL_REVIEW. Admin은 자유 텍스트만 보고 수동 처리. |
| **다의적 메시지** | "일정이랑 견적 둘 다 바꾸고 싶어요" → 복수 intent/복수 액션 추천 허용. Admin이 "설문 재개 먼저" / "견적만 수정" 등 순서 선택. |
| **언어 혼합/오타** | LLM이 다국어 입력을 처리하도록 프롬프트 설계. 실패 시 원문 그대로 Analysis에 저장하고 intent=URGENT_ADMIN_REVIEW. |
| **감사/규정** | 모든 상태 변경은 Admin 사용자 기준으로 ActionLog에 기록. LLM raw 응답은 옵션으로 보관(개인정보 마스킹 정책 적용). |
| **기존 플로우 호환** | `api_quote_request_revision`은 그대로 두고, 내부에서 QuoteChangeRequest 생성 + (비동기 또는 동기) LLM 호출만 추가. 기존처럼 메시지함에 메시지가 쌓이고 quote.status=NEGOTIATING 유지. |

---

*문서 끝.*
