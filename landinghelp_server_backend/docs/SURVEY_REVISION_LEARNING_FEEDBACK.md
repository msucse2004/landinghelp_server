# 설문 수정 흐름 학습용 Feedback 및 Label 문서

설문 수정 요청부터 실제 수정 저장·피드백까지 한 흐름을 `request_id`로 묶어 이벤트를 수집하고, 학습용 label/summary를 생성하는 구조를 설명합니다.

---

## 1. 새로 추가한 이벤트 종류

모든 이벤트는 `CustomerRequestFeedbackEvent` 모델에 저장되며, `event_type`으로 구분합니다.

| event_type | 설명 | 주요 메타데이터/필드 |
|------------|------|----------------------|
| **message_received** | 사용자 수정 요청 메시지 수신 (흐름의 시작) | `message_text`: 원문 (일부만 저장 가능) |
| **route_predicted** | 휴리스틱/LLM 추천 페이지 예측 완료 | `user_message`, `heuristic_result`, `llm_result`, `merged_candidates`, `selected_primary_page`, `recommendation_confidence` |
| **suggestion_clicked** | 사용자가 추천 항목(예: 설문 수정하기) 클릭 | `suggested_page_key`, `clicked_item` |
| **page_viewed** | 설문 특정 단계(페이지) 진입 | `page_key`, `viewed_at`, `source` (suggestion \| manual_navigation \| deep_link) |
| **edit_saved** | 특정 페이지에서 수정 저장 API 호출 결과 | `page_key`, `save_result` (success \| failure), `changed_fields`, `entity_type`, `entity_id` |
| **feedback_clicked** | 사용자 명시 피드백 버튼 클릭 | `value`: corrected_here \| used_other_page \| could_not_find |

- **feedback_clicked.value**
  - `corrected_here`: 여기서 수정했어요
  - `used_other_page`: 다른 페이지에서 했어요
  - `could_not_find`: 못 찾겠어요

---

## 2. request_id 흐름 설명

- **생성**: 사용자가 수정 요청 메시지를 보내면 `handle_customer_request_flow()` 진입 시 `request_id = uuid.uuid4().hex` 로 한 번만 생성.
- **전달**: API 응답(`POST /api/messaging/.../messages/`)의 `body.request_id`로 프론트에 전달. 제안(offer) 객체에도 `request_id` 포함.
- **일관성**: 동일 수정 요청에 대한 “추천 클릭 → 설문 진입 → 저장 → 피드백”을 하나의 세션으로 묶기 위해, 모든 후속 요청(설문 URL, 저장 API, 피드백 API)에 같은 `request_id`를 붙입니다.
- **타임라인**: `messaging.feedback_events.get_event_timeline(request_id)` 로 해당 세션의 이벤트를 시간순 조회.
- **누락 시**: `request_id`가 없으면 이벤트 저장을 스킵하고, 설문/저장/피드백 등 메인 기능은 그대로 동작(graceful fallback).

```
[사용자 메시지] → message_received (request_id 생성·저장)
       ↓
[분류·추천]     → route_predicted (추천 후보·1순위 저장)
       ↓
[추천 클릭]     → suggestion_clicked (suggested_page_key)
       ↓
[설문 진입]     → page_viewed (page_key, source)
       ↓
[저장]         → edit_saved (page_key, save_result)
       ↓
[피드백 버튼]   → feedback_clicked (value)
```

---

## 3. 실제 학습 label 생성 기준

`messaging.learning_labels.build_learning_summary(request_id)` 가 이벤트를 집계해 다음 규칙으로 label/요약을 만듭니다.

- **positive_labels (긍정 label)**
  - **strong**: `edit_saved` 가 success 인 `page_key` 들 → 실제로 수정한 페이지.
  - **weak**: `edit_saved` 없이 `suggestion_clicked` 만 있으면, 클릭한 추천 페이지(`suggested_page_key`)를 weak positive로 사용.
- **negative_labels (부정 label)**
  - `feedback_clicked.value == "used_other_page"` 이고, 실제 저장이 **다른** 페이지에서 일어났을 때, **추천했던 1순위 페이지**를 negative로 기록.
- **recommendation_failure**
  - `feedback_clicked.value == "could_not_find"` 이면 True. 추천 실패로 분류.
- **label_quality**
  - **strong**: `edit_saved` success 가 1건 이상 있음 (ground truth 있음).
  - **medium**: `feedback_clicked` 가 있음 (corrected_here / used_other_page / could_not_find).
  - **weak**: `suggestion_clicked` 또는 `page_viewed` 만 있고, edit_saved·feedback_clicked 없음.

multi-step(여러 페이지 연속 수정)인 경우:

- **actual_edit_page**: 첫 번째 `edit_saved` success 의 `page_key` (단일 대표값).
- **all_edit_saved_pages**: 해당 `request_id` 내 모든 `edit_saved` success 의 `page_key` 리스트.
- 학습 시 multi-step 은 `all_edit_saved_pages` / `positive_labels` 를 사용하는 것을 권장.

---

## 4. strongest signal이 edit_saved 인 이유

- **의도와 행동의 일치**: “어디를 수정하고 싶다”는 말(메시지/추천 클릭)보다, “실제로 어디에서 저장했는가”가 사용자 의도의 직접적인 증거입니다.
- **노이즈 감소**: 추천만 클릭하고 다른 페이지에서 저장한 경우, 실제 저장 페이지가 진짜 target이 되므로, 저장 이벤트를 기준으로 하면 잘못된 positive를 줄일 수 있습니다.
- **명시적 행동**: 저장은 사용자가 폼을 작성하고 저장 버튼을 누른 명시적 행동이라, 클릭/조회보다 신호가 명확합니다.

따라서 학습 시 **정답(positive) target** 은 `edit_saved` success 의 `page_key`(및 `all_edit_saved_pages`)를 우선 사용하고, 추천 클릭/페이지 조회는 보조 신호로 활용합니다.

---

## 5. top-k 후보 저장 이유

- **ranking 학습**: “1순위만 맞추기”가 아니라 “실제 정답이 2·3순위에 있었는지”까지 알면, ranking/reranking 모델 학습에 활용할 수 있습니다.
- **실패 분석**: 추천 1순위가 틀렸어도, 실제 수정 페이지가 top-k 안에 있었는지 여부로 모델 개선 포인트를 파악할 수 있습니다.
- **raw signal 보존**: 휴리스틱 결과(`heuristic_result`)와 LLM 결과(`llm_result`)를 각각 저장하고, `merged_candidates`(예: top 3)로 병합해 두었기 때문에, 나중에 휴리스틱/LLM 비중 조정이나 앙상블 전략을 바꿀 수 있습니다.

`route_predicted` 이벤트의 metadata 에 `merged_candidates`, `heuristic_result`, `llm_result`, `selected_primary_page` 가 들어가며, `CustomerRequestIntentAnalysis.route_candidates` 에도 동일한 구조가 저장됩니다.

---

## 6. 프론트에서 request_id와 tracking event 넘기는 방법

### 6.1 request_id 획득

- **메시지 전송 후**: `POST /api/messaging/conversations/<id>/messages/` 응답 body 에 `request_id` 가 있으면 저장해 두고, 같은 흐름에서 계속 사용.

### 6.2 설문으로 이동할 때 (추천 클릭)

- **inbox 등**: 제안(offer)의 `request_id` 를 사용해, 설문 진입 URL에 쿼리로 붙입니다.
  - 예: `redirectUrl += '?request_id=' + encodeURIComponent(o.request_id)`
  - 추천을 통해 들어왔음을 표시: `&from=suggestion` 도 함께 붙이면, `page_viewed` 의 `source` 가 `suggestion` 으로 기록됩니다.

### 6.3 설문 단계 이동·저장

- **GET (단계 페이지)**: 설문 step URL 에 `request_id`(및 필요 시 `from`) 쿼리 유지.
  - 예: `/settlement/survey/step/2/?request_id=xxx&from=suggestion`
- **POST (단계 저장)**: 폼에 `name="request_id"` 인 hidden input 으로 `request_id` 전송.
- **최종 제출**: 제출용 폼에도 동일한 `request_id` hidden input 포함해 전송.

### 6.4 피드백 버튼

- 설문 수정 안내 화면의 피드백 버튼 클릭 시:
  - `POST /settlement/survey/feedback/` (survey_revision_feedback)
  - Body (JSON): `{ "request_id": "<request_id>", "value": "corrected_here" | "used_other_page" | "could_not_find", "page_key": "<optional>" }`
- `request_id` 는 같은 페이지의 `data-request-id`(또는 hidden input)에서 읽어 보냅니다.

### 6.5 정리

| 구간 | request_id 전달 방법 |
|------|----------------------|
| 메시지 → 프론트 | 응답 body.request_id |
| 추천 클릭 → 설문 URL | 쿼리 `?request_id=...&from=suggestion` |
| 설문 단계 이동 | GET 쿼리 유지 (다음/이전 시 URL에 request_id 포함) |
| 단계 저장/제출 | POST form field `request_id` |
| 피드백 API | JSON body `request_id` |

---

## 7. 향후 ML 학습 파이프라인 연결 방법 제안

1. **데이터 수집**
   - 이미 수집 중: `CustomerRequestFeedbackEvent` (타임라인), `CustomerRequestLearningSummary` (request_id 단위 요약).
   - 필요 시 주기적으로 `build_learning_summary(request_id)` 또는 `get_or_build_learning_summary(request_id)` 호출해 summary 테이블 갱신.

2. **학습 데이터 추출**
   - `CustomerRequestLearningSummary` 를 쿼리해 `label_quality == 'strong'` 위주로 export (필요 시 medium 포함).
   - 각 레코드의 `summary` JSON 에서:
     - 입력: `user_message`, `predicted_candidates` (또는 heuristic/llm raw)
     - 정답: `actual_edit_page` 또는 `all_edit_saved_pages` / `positive_labels`
     - negative 샘플: `negative_labels`
     - 메타: `recommendation_failure`, `feedback_type`, `label_quality`

3. **모델 태스크**
   - **분류**: user_message → 실제 수정 페이지(page_key) 예측.
   - **ranking**: user_message + 후보 리스트 → 실제 수정 페이지 순위 학습 (positive_labels, negative_labels 활용).

4. **연동 포인트**
   - `messaging.learning_labels.build_learning_summary` / `get_or_build_learning_summary` → 동일 인터페이스로 배치/스크립트에서 호출.
   - Admin/debug: `GET /admin/debug/request-flow/api/?request_id=xxx` 로 상세 확인 가능.
   - Django Admin: `CustomerRequestLearningSummary` 목록에서 `label_quality` 필터 후 export.

5. **품질 필터**
   - 학습 시 `label_quality == 'strong'` 만 사용하거나, `recommendation_failure == False` 인 샘플만 사용하는 식으로 필터링 권장.

---

## 8. 테스트

- **파일**: `messaging/tests/test_survey_revision_feedback_flow.py`
- **실행**: `python manage.py test messaging.tests.test_survey_revision_feedback_flow --verbosity=2` (또는 `--keepdb` 로 DB 유지)
- **시나리오**: request_id 생성, route_predicted/suggestion_clicked/page_viewed/edit_saved/feedback_clicked 저장, actual_edit_page 추론, 추천≠실제 시 negative label, LLM 실패 시 heuristic fallback, request_id 없을 때 안전 동작, multi-step 요약, 타임라인 집계

---

## 9. 관련 코드 위치

| 역할 | 파일/위치 |
|------|-----------|
| 이벤트 모델 | `messaging.models.CustomerRequestFeedbackEvent` |
| 이벤트 저장/조회 | `messaging.feedback_events` (log_* , get_event_timeline, get_events_by_request) |
| 학습 요약/라벨 | `messaging.learning_labels` (build_learning_summary, get_or_build_learning_summary, build_request_flow_detail) |
| 요약 저장 모델 | `messaging.models.CustomerRequestLearningSummary` |
| request_id 생성·전달 | `customer_request_service.handle_customer_request_flow`, `messaging.views` (메시지 API 응답) |
| 설문 저장 시 edit_saved | `survey.views._record_edit_saved`, `survey_step_save` |
| 설문 페이지/진입 | `survey.views.survey_start`, `survey_step` (page_viewed, request_id/from 쿼리) |
| 피드백 API | `survey.views.survey_revision_feedback` |
| Admin/debug API·화면 | `messaging.views.api_request_flow_detail`, `debug_request_flow_page`; `/admin/debug/request-flow/` |

---

## 10. TODO (다음 작업 이어가기)

- [ ] **ML export 스크립트**: `CustomerRequestLearningSummary` 또는 이벤트에서 학습용 CSV/JSON export (label_quality, recommendation_failure 필터 옵션 포함).
- [ ] **배치 요약 갱신**: 새 이벤트가 쌓인 request_id에 대해 주기적으로 `get_or_build_learning_summary` 호출해 summary 테이블 동기화 (선택).
- [ ] **dwell time**: `page_viewed` 와 다음 이벤트(또는 page leave) 간 시간을 저장해, “빠른 이탈” weak negative 보강.
- [ ] **“다른 페이지에서 했어요” 확장**: 클릭 시 다른 수정 페이지 링크 목록 노출 (프론트 확장 포인트 이미 있음).
- [ ] **“못 찾겠어요” fallback**: admin review 또는 문의 플로우 연결 (data-fallback-url 등 확장 포인트 있음).
- [ ] **개인정보 검토**: 학습/export 시 message_text, user_id 등 노출 범위 정책 확정 및 필요 시 익명화/길이 제한 재검토.
