# Step 11 — 최종 통합 패스 (Survey → LSA → Contract → Execution)

이 문서는 Step 11 기준 최종 통합 상태를 정리합니다.

## 1) End-to-End Workflow (실제 연결 경로)

1. Customer 설문 제출
   - Entry: `survey/views.py::survey_submit`
2. 시스템 Draft Schedule 생성(대면 Agent 서비스 중심)
   - Entry: `settlement/scheduling_engine.py::ensure_submission_schedule_draft`
3. Admin 캘린더 워크벤치에서 드래그/수정
   - Page/API: `config/schedule_admin_views.py::submission_review_schedule`, `submission_review_schedule_api`
4. Admin 조정안 스냅샷으로 LSA 배치 발송
   - Entry: `config/schedule_admin_views.py::submission_review_schedule_send_lsa`
   - Service: `settlement/lsa_service.py::send_lsa_batch_for_schedule_plan`
5. Agent 응답 입력(accept/suggest/decline)
   - View/API: `settlement/views_lsa_response.py::agent_lsa_response_input`, `agent_lsa_response_submit`
6. Admin 1명 선정 + 계약 실행
   - Entry: `config/schedule_admin_views.py::submission_review_lsa_select_agent`
   - Service: `settlement/lsa_service.py::select_lsa_agent_for_contract`
7. 미선정 Agent 정중 통지
   - Service: `settlement/lsa_service.py::_notify_agent_lsa_not_selected`
8. 선정 Agent 계약 패키지 전달
   - Service: `settlement/lsa_service.py::_deliver_contract_to_selected_agent`
9. Final Execution Schedule 생성
   - Service: `settlement/lsa_service.py::generate_final_execution_schedule`
10. Role-aware calendar 제공
   - Admin: schedule workbench full metadata
   - Agent: 본인 assigned ACTIVE execution item만
   - Customer: customer-safe schedule only
11. 선정 Agent를 customer-admin shared thread에 합류
   - Service: `settlement/lsa_service.py::_expand_existing_shared_conversation_for_contract` (idempotent)

---

## 2) Draft Schedule Lifecycle

- `DRAFT` (system draft)
  - 설문 제출 직후 자동 생성.
- `REVIEWING` (admin adjusted draft)
  - Admin 첫 저장 시 DRAFT를 기반으로 revision clone 생성(`based_on`/`based_on_item` 보존).
- `FINALIZED` (LSA sent draft)
  - LSA 발송 시점 스냅샷 기준 draft 확정.
- `SENT` / `ACTIVE`
  - 고객 반영/실행 스케줄 단계.

핵심 원칙:
- 원본 draft/history는 보존하고, admin 조정/실행 플랜은 분리 관리.
- 이후 실행 source of truth는 `LsaAgentContract.execution_schedule_plan`.

---

## 3) LSA Snapshot Model

주요 모델:
- `LsaSourcingBatch`
  - `proposed_schedule_snapshot`
  - `requested_services_snapshot`
  - `internal_pricing_snapshot`
  - `schedule_version`
- `LsaAgentRequest`
  - Agent별 payload 스냅샷과 상태(`SENT/RESPONDED/DECLINED/SELECTED/NOT_SELECTED/CANCELLED`)

스냅샷 규칙:
- 발송 시점 스냅샷은 immutable 취급.
- 발송 후 admin draft 수정이 있어도 기존 batch/request payload는 변경하지 않음.

---

## 4) Agent Response Model

주요 모델:
- `LsaAgentResponse`
  - `decision`: `ACCEPT_AS_IS` / `PARTIAL` / `DECLINE`
  - `revision` 이력 보존
- `LsaAgentResponseItem`
  - item별 `action`: `ACCEPT` / `SUGGEST_CHANGE` / `UNAVAILABLE`
  - 변경 제안 시 suggested times 필수

입력 제약:
- 토큰 기반 접근 검증(`build_lsa_response_token`/`verify_lsa_response_token`).
- 요청 대상 Agent 본인만 응답 가능.

---

## 5) Final Execution Schedule Rules

- 생성 시점: Admin 선정/계약 완료 직후.
- 생성 대상: 새로운 `ServiceSchedulePlan(status=ACTIVE)`.
- 데이터 원천:
  - baseline: admin draft snapshot plan
  - selected response가 제안 변경(`SUGGEST_CHANGE`)이면 승인 규칙에 따라 시간 반영
- assignment 규칙:
  - `IN_PERSON_AGENT`는 선정 Agent로 배정
- 보안/노출:
  - customer 반영은 `plan_to_legacy_schedule(..., customer_safe=True)` 사용
  - 내부 협상 메타(notes/source_reason 등) 노출 금지

---

## 6) Role-based Calendar Visibility

- Admin
  - day/week/month, 검색(q), anchor_date, items_in_view 지원
  - recommendation metadata 표시 가능
- Agent
  - 본인 `assigned_agent` + `ACTIVE` execution item만 dashboard 노출
- Customer
  - customer-safe schedule만 노출(민감 메타 제거)

---

## 7) 통합 테스트 커버리지

핵심 테스트 묶음:
- `settlement/tests/test_full_workflow_lsa_integration.py`
  - 1~11 단계 E2E 통합 시나리오
- `settlement/tests/test_lsa_schedule_snapshot.py`
- `settlement/tests/test_lsa_agent_response.py`
- `settlement/tests/test_lsa_agent_contract_selection.py`
- `settlement/tests/test_lsa_contract_notifications.py`
- `settlement/tests/test_final_execution_schedule.py`
- `settlement/tests/test_calendar_workbench_and_role_visibility.py`

검증 기준:
- API/서비스/뷰 연결, 상태 전이, role-safe 노출, thread 확장(idempotent)까지 포함.

---

## 8) 마이그레이션 목록 (신규 워크플로우 관련)

- `settlement/migrations/0027_schedule_item_recommendation_metadata.py`
- `settlement/migrations/0028_schedule_plan_item_version_lineage.py`
- `settlement/migrations/0029_lsa_sourcing_models.py`
- `settlement/migrations/0030_lsa_agent_response_models.py`
- `settlement/migrations/0031_lsa_batch_contract_selection.py`
- `settlement/migrations/0032_lsa_contract_execution_plan.py`

---

## 9) Known Limitations / TODO

- month view에서 상세 편집 UX(밀도 높은 카드 편집)는 day/week 대비 제한적.
- join message는 idempotent 동작으로, Agent가 이미 thread 참여자인 경우 추가 join message를 만들지 않음.
- 메시지/이메일 텍스트 일부 하드코딩 문구는 i18n 키로 추가 정리 여지 있음.
- 장기적으로는 LSA batch review에서 suggestion approve granularity UI(항목 단위 승인 옵션) 고도화 가능.
