# Step 13 — Final Integration Pass Report

이 문서는 Step 13 최종 통합 패스 결과를 정리합니다.

## 1) 통합 테스트 결과

- 실행 범위: historical recommendation → admin schedule workbench → LSA snapshot send → agent structured response → contract selection → final execution schedule → notifications/thread expansion → role visibility.
- 결과: `Found 51 test(s)` / `Ran 51 tests` / `OK`.
- 결론: Step 9~12 기능 연결은 통합 관점에서 정상 동작.

---

## 2) Historical Training Data Definition

학습/추천용 historical data는 `settlement/schedule_training_data.py`에서 중앙 정의합니다.

포함 조건:
- `ServiceSchedulePlan.status in (SENT, ACTIVE)`
- `entry_date` 컨텍스트 확보 가능
- training 대상 item이 complete (`service_code`, `starts_at`, `ends_at` 유효)

제외 조건:
- `DRAFT/REVIEWING/FINALIZED(LSA snapshot draft)`
- partial/corrupted item 포함 플랜
- entry_date 없는 플랜

핵심 함수:
- `get_training_eligible_schedule_items`
- `get_training_eligible_historical_examples`

---

## 3) Feature Extraction

현재 submission + historical row 정규화는 `settlement/schedule_features.py`가 담당합니다.

핵심 피처:
- 지역: `state_code`, `city`, canonical `region`
- 시간: `entry_date`, `remaining_days_to_entry`
- 서비스 집합: required/optional/quote 코드 normalize
- 전달 모드: `service_types_by_code`, in-person/ai/self mix count
- 의존 민감 서비스: `dependency_sensitive_service_codes`
- 고객 프로필: household, 목적, special requirements, preferred support mode

핵심 함수:
- `build_current_submission_feature_context`
- `build_historical_schedule_feature_contexts`

---

## 4) Recommendation Layers

추천 레이어는 `settlement/scheduling_engine.py::recommend_schedule_placements`에 통합되어 있습니다.

레이어 순서:
1. historical match (similarity 기반)
2. statistical prior (service-day offset, sequence/grouping prior)
3. deterministic fallback

추가 정책:
- remaining-days profile (`urgent/normal/long`) 기반 spacing/offset 제약
- grouping/sequence prior 반영
- `needs_admin_review` 플래그 및 recommendation metadata 저장

---

## 5) Draft Lifecycle Separation

일정 라이프사이클은 working draft와 execution plan을 분리합니다.

- `DRAFT`: system draft
- `REVIEWING`: admin adjusted draft (clone + lineage)
- `FINALIZED`: LSA sent immutable snapshot draft
- `ACTIVE`: selected agent 기준 final execution schedule

lineage 필드:
- `ServiceSchedulePlan.based_on`
- `ServiceScheduleItem.based_on_item`

핵심 원칙:
- admin working draft/history는 보존
- 최종 실행 source of truth는 `LsaAgentContract.execution_schedule_plan`

---

## 6) LSA Snapshot & Agent Response

LSA snapshot 전송/응답 구조:
- batch: `LsaSourcingBatch`
- request: `LsaAgentRequest`
- response: `LsaAgentResponse` + `LsaAgentResponseItem`
- contract: `LsaAgentContract`

스냅샷 불변성:
- LSA 발송 시점 payload/snapshot은 immutable 취급
- 발송 후 admin 수정이 있어도 기존 batch/request payload는 변하지 않음

감사추적 보강 payload 필드:
- `proposed_schedule_plan_id`
- `based_on_schedule_plan_id`
- `root_recommended_schedule_plan_id`

---

## 7) Final Execution Schedule Rules

최종 실행 일정 생성 규칙 (`generate_final_execution_schedule`):
- baseline: selected batch의 finalized snapshot plan
- selected response의 `SUGGEST_CHANGE`는 승인 규칙에 따라 반영
- `IN_PERSON_AGENT` 항목은 selected agent로 배정
- final item 상태는 `CONFIRMED`

고객 반영/노출 보안:
- `plan_to_legacy_schedule(..., customer_safe=True)` 사용
- 내부 negotiation metadata(notes/location/source reason 등) 비노출

---

## 8) Step13 Deliverables Inventory

### 8.1 Changed files (핵심)

- 워크플로 서비스/뷰
  - `settlement/lsa_service.py`
  - `settlement/views_lsa_response.py`
  - `config/schedule_admin_views.py`
  - `config/urls.py`
  - `settlement/schedule_utils.py`
  - `settlement/scheduling_engine.py`
  - `settlement/schedule_features.py`
  - `settlement/schedule_training_data.py`
- 모델/마이그레이션
  - `settlement/models.py`
  - `settlement/migrations/0027~0033`
- 템플릿/UI
  - `templates/app/admin_schedule.html`
  - `templates/app/admin_lsa_batch_review.html`
  - `templates/app/agent_lsa_response.html`
  - `templates/app/agent_dashboard.html`
  - `templates/app/customer_dashboard.html`
- 테스트
  - `settlement/tests/test_full_workflow_lsa_integration.py`
  - `settlement/tests/test_lsa_schedule_snapshot.py`
  - `settlement/tests/test_lsa_agent_response.py`
  - `settlement/tests/test_lsa_agent_contract_selection.py`
  - `settlement/tests/test_lsa_contract_notifications.py`
  - `settlement/tests/test_final_execution_schedule.py`
  - `settlement/tests/test_calendar_workbench_and_role_visibility.py`
  - `settlement/tests/test_schedule_lifecycle_separation.py`
  - `settlement/tests/test_schedule_training_data_definition.py`
  - `settlement/tests/test_schedule_feature_extraction.py`
  - `settlement/tests/test_scheduling_engine_historical_recommendation.py`
  - `settlement/tests/test_schedule_recommendation_metadata_persistence.py`
  - `settlement/tests/test_schedule_draft_on_survey_submit.py`
  - `settlement/tests/test_schedule_draft_versioning.py`
  - `settlement/tests/test_remaining_days_recommendation.py`

### 8.2 Migrations added

- `settlement/migrations/0027_schedule_item_recommendation_metadata.py`
- `settlement/migrations/0028_schedule_plan_item_version_lineage.py`
- `settlement/migrations/0029_lsa_sourcing_models.py`
- `settlement/migrations/0030_lsa_agent_response_models.py`
- `settlement/migrations/0031_lsa_batch_contract_selection.py`
- `settlement/migrations/0032_lsa_contract_execution_plan.py`
- `settlement/migrations/0033_schedule_item_recommendation_metadata_json.py`

### 8.3 Dead code path 정리

- 제거됨:
  - `settlement/views.py::get_agents_for_survey_fragment`
  - `settlement/views.py::api_available_agents_for_survey`
  - `config/urls.py`의 `/api/settlement/survey-agents/` 라우트
- 근거: 내부 참조 없음(설문 단계가 admin_assign 고정으로 전환됨).

---

## 9) Known Limitations / TODO

- month view는 day/week 대비 세밀한 카드 편집 UX가 제한적.
- selected response의 항목별 승인 granularity UI(부분 승인/부분 보류)는 향후 개선 여지.
- 일부 메시지/이메일 문구 i18n key 정리는 추가 가능.
