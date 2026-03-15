# 설문 수정 흐름 학습 피드백 (E2E 테스트 가이드)

## 개요
이 문서는 설문 수정 요청 흐름의 **request_id 전파**, **이벤트 로깅**, **학습 요약 생성**을 검증하는 E2E(엔드-투-엔드) 통합 테스트 가이드입니다.

---

## 구현 상태

### ✅ 완료된 것
1. **request_id 전파 경로**: GET → session → POST 흐름 구현
2. **페이지 진입 로깅**: `survey_step` 진입 시 `page_viewed` 이벤트 기록
3. **저장 이벤트**: `survey_step_save` 성공 시 `edit_saved` 이벤트 기록
4. **피드백 API**: `survey_revision_feedback` POST 시 `feedback_clicked` 이벤트 기록
5. **학습 요약**: `actual_edit_page`, `positive_labels`, `negative_labels` 추론
6. **E2E 통합 테스트**: 실제 view 호출을 통한 시나리오 검증
7. **CSRF 부트스트랩**: 테스트용 CSRF 토큰 획득 helper 추가

### ⚠️ 주의사항
- **설문 마이그레이션**: 첫 실행 시 `--keepdb` 옵션으로 시간 단축 가능
- **request_id 필수**: request_id가 없으면 이벤트 저장 안 됨 (graceful fallback)
- **CSRF 쿠키**: 테스트 실행 시 `bootstrap_csrftoken_from_survey_api()` 사용 권장

---

## 테스트 시나리오

### 시나리오 A: 단일 페이지 진입 → 저장 → 요약
**목표**: 한 페이지에서 데이터 저장 시 이벤트 체인 확인

**흐름**:
1. `GET /survey/step/1/?request_id=xxx` → `page_viewed` 이벤트 저장
2. `POST /survey/step/1/save/` → `edit_saved` 이벤트 저장
3. `build_learning_summary(request_id)` → `actual_edit_page` 추론

**테스트 코드**:
```python
def test_scenario_a_page_viewed_edit_saved_summary(self):
    # 설문 step 1 진입
    resp = client.get(survey_step(step=1), {"request_id": request_id})
    assert page_viewed_event_saved()
    
    # 데이터 저장
    resp = client.post(survey_step_save(step=1), {..., "request_id": request_id})
    assert edit_saved_event_saved()
    
    # 학습 요약 확인
    summary = build_learning_summary(request_id)
    assert summary["actual_edit_page"] == "applicant_info"
    assert summary["label_quality"] == "strong"
```

### 시나리오 B: 다중 페이지 순회 + 피드백
**목표**: 여러 페이지 이동 후 피드백 클릭 시 타임라인 순서 검증

**흐름**:
1. Step 1 진입 & 저장
2. Step 2 진입 & 저장 (session request_id 유지)
3. Feedback API: `POST /survey/feedback/` → `feedback_clicked` 이벤트
4. 타임라인: `page_viewed → edit_saved → feedback_clicked` 순서 확인

**실행**:
```bash
python manage.py test messaging.tests.test_survey_revision_feedback_flow.SurveyRevisionFeedbackE2ETests.test_scenario_b_multi_step_with_feedback --keepdb
```

### 시나리오 C: session request_id 전파
**목표**: 첫 GET에서 받은 request_id가 session에 저장되고 POST에 영향을 미쳤는지 검증

**흐름**:
1. `GET /survey/step/1/?request_id=xxx` → session에 저장
2. `POST /survey/step/1/save/` (request_id 필드 없음) → session에서 가져옴
3. 이벤트 확인: request_id 일치

---

## 테스트 실행 방법

### 1. 전체 E2E 테스트 실행 (추천)
```bash
cd /path/to/landinghelp_server
python manage.py test messaging.tests.test_survey_revision_feedback_flow.SurveyRevisionFeedbackE2ETests --keepdb --verbosity=2
```

**출력 예**:
```
Ran 4 tests in 11.288s
OK
```

### 2. 특정 시나리오만 실행
```bash
# 시나리오 A
python manage.py test messaging.tests.test_survey_revision_feedback_flow.SurveyRevisionFeedbackE2ETests.test_scenario_a_page_viewed_edit_saved_summary --keepdb

# 시나리오 B
python manage.py test messaging.tests.test_survey_revision_feedback_flow.SurveyRevisionFeedbackE2ETests.test_scenario_b_multi_step_with_feedback --keepdb

# 시나리오 C
python manage.py test messaging.tests.test_survey_revision_feedback_flow.SurveyRevisionFeedbackE2ETests.test_scenario_c_request_id_session_propagation --keepdb
```

### 3. 기존 단위 테스트 포함 전체 실행
```bash
python manage.py test messaging.tests.test_survey_revision_feedback_flow --keepdb --verbosity=1
```

**예상 결과**:
- 총 19개 테스트 (기존 15개 + 신규 E2E 4개)
- 모두 `OK` 상태

---

## request_id 전파 흐름 (최종)

```
┌─────────────────────────────────────────┐
│ 고객 메시지 수신                           │
│ (handle_customer_request_flow)            │
│ ▼ request_id 생성 (UUID)                │
└─────────────────────────────────────────┘
                    │
                    ▼
            ┌──────────────────┐
            │ Inbox UI 제시     │
            │ (action_offers)   │
            │ - request_id 포함 │
            └──────────────────┘
                    │
                    ▼ "설문 수정하기" 클릭
        ┌──────────────────────────────┐
        │ GET /survey/step/1/           │
        │ ?request_id=xxxxxxxx-xxxx     │
        │ ▼ Query 파라미터 수신          │
        │ session["survey_request_id"]  │
        │ = request_id 저장             │
        └──────────────────────────────┘
                    │
                    ▼
        ┌──────────────────────────────┐
        │ survey_wizard.html 렌더        │
        │ - context.request_id 포함     │
        │ - <input name="request_id"    │
        │   value="{{ request_id }}">   │
        │ - prev/next 링크에도 포함      │
        │ ?request_id=xxxxxxxx-xxxx     │
        └──────────────────────────────┘
                    │
                    ▼ 페이지 진입
        ┌──────────────────────────────┐
        │ log_page_viewed()             │
        │ - request_id 기록            │
        │ - page_key: "applicant_info" │
        │ - source: "suggestion" (또는 └─────────────────────────
                   "manual_navigation")  │
        │ - CustomerRequestFeedbackEvent│
        │   저장                        │
        └──────────────────────────────┘
                    │
                    ▼ 폼 작성 후 저장 클릭
        ┌──────────────────────────────┐
        │ POST /survey/step/1/save/     │
        │ - form.request_id 포함        │
        │   (또는 session 폴백)         │
        │ - form.first_name 등 데이터   │
        │ ▼ 데이터 검증 & DB 저장       │
        └──────────────────────────────┘
                    │
                    ▼ 저장 성공
        ┌──────────────────────────────┐
        │ log_edit_saved()              │
        │ - request_id 기록            │
        │ - page_key: "applicant_info" │
        │ - save_result: "success"      │
        │ - changed_fields: [...]       │
        │ ▼ CustomerRequestFeedbackEvent
        │   저장                        │
        └──────────────────────────────┘
                    │
                    ▼
        ┌──────────────────────────────┐
        │ 피드백 버튼 노출               │
        │ (is_revision_requested 시)    │
        │ - "여기서 수정했어요"         │
        │ - "다른 페이지에서 했어요"    │
        │ - "못 찾겠어요"              │
        └──────────────────────────────┘
                    │
                    ▼ 피드백 선택
        ┌──────────────────────────────┐
        │ POST /survey/feedback/        │
        │ (JSON):                       │
        │ {                             │
        │   "request_id": "xxx",       │
        │   "value": "corrected_here"   │
        │ }                             │
        │ ▼ 피드백 저장                  │
        └──────────────────────────────┘
                    │
                    ▼
        ┌──────────────────────────────┐
        │ log_feedback_clicked()        │
        │ - request_id 기록            │
        │ - value: "corrected_here"    │
        │ ▼ CustomerRequestFeedbackEvent
        │   저장                        │
        └──────────────────────────────┘
                    │
                    ▼
        ┌──────────────────────────────┐
        │ 학습 요약 생성                 │
        │ build_learning_summary(rid)   │
        │ - actual_edit_page:           │
        │   "applicant_info"           │
        │ - label_quality: "strong"    │
        │ - positive_labels: [...]     │
        │ - negative_labels: [...]     │
        │ ▼ CustomerRequestLearningSummary
        │   저장                        │
        └──────────────────────────────┘
```

---

## CSRF 토큰 관리

### 테스트에서 CSRF 토큰 얻기

**방법 1: 헬퍼 함수 사용 (권장)**
```python
from messaging.tests.test_survey_revision_feedback_flow import bootstrap_csrftoken_from_survey_api

client = Client()
client.force_login(user)
csrf_token = bootstrap_csrftoken_from_survey_api(client)
# 이후 POST에 사용
resp = client.post(url, data={..., "csrfmiddlewaretoken": csrf_token})
```

**방법 2: 직접 GET 후 추출**
```python
resp = client.get(reverse("survey:survey_start"))
csrf_cookie = resp.cookies.get("csrftoken")
csrf_token = csrf_cookie.value if csrf_cookie else None
```

---

## 성능 최적화

### --keepdb 옵션 사용 (권장)
```bash
python manage.py test ... --keepdb
```

**효과**:
- 첫 실행만 마이그레이션 (약 5초)
- 이후 실행은 기존 DB 재사용 (약 11초)

### 테스트 실행 시간
| 명령 | 시간 | 비고 |
|-----|------|------|
| 첫 실행 (--keepdb 미적용) | ~30초 | 마이그레이션 포함 |
| 두 번째 실행 (--keepdb 적용) | ~11초 | DB 재사용 |
| 특정 테스트만 | ~5-20초 | 테스트 복잡도에 따라 |

---

## 엣지 케이스 및 검증

### ✅ 검증된 것
- [x] request_id 없을 때 → 이벤트 미저장 (graceful)
- [x] 페이지 진입 없이 바로 저장 → edit_saved만 기록
- [x] session request_id 폴백 → POST에 request_id 필드 없어도 작동
- [x] prev_step 링크 → request_id 유지
- [x] CSRF 쿠키 없음 → bootstrap helper로 해결

### ⚠️ 아직 미검증
- 동일 request_id로 3개 이상 연속 저장 시 all_edit_saved_pages 정렬
- feedback_clicked 이후 다시 저장했을 때 이벤트 순서
- 매우 긴 request_id (64자 제한 테스트)

---

## 문제 해결

### "page_viewed 이벤트가 저장되지 않음"
**원인**: request_id가 none 또는 빈 문자열
**해결**:
```python
# 확인
request_id = (request_id or "").strip()
assert request_id, "request_id는 필수"

# GET에 포함
resp = client.get(survey_step, {"request_id": request_id})
```

### "edit_saved 이벤트가 저장되지 않음"
**원인**: survey_step_save가 500 에러 반환
```python
resp = client.post(...)
if resp.status_code != 200:
    data = resp.json()  # 또는 resp.content 확인
    print(f"Error: {data}")
```

### "CSRF token is missing"
**원인**: CSRF 쿠키를 못 받음
```python
# 해결
csrf_token = bootstrap_csrftoken_from_survey_api(client)
assert csrf_token, "CSRF 토큰을 얻을 수 없음"
```

---

## 참고: 관련 파일

| 파일 | 역할 |
|-----|------|
| [survey/views.py](../survey/views.py) | survey_start, survey_step, survey_step_save, survey_revision_feedback |
| [survey/templates/survey/survey_wizard.html](../survey/templates/survey/survey_wizard.html) | request_id hidden input, prev/next 링크 |
| [messaging/feedback_events.py](../messaging/feedback_events.py) | log_page_viewed, log_edit_saved, log_feedback_clicked |
| [messaging/learning_labels.py](../messaging/learning_labels.py) | build_learning_summary, actual_edit_page 추론 |
| [messaging/models.py](../messaging/models.py) | CustomerRequestFeedbackEvent, CustomerRequestLearningSummary |
| [messaging/tests/test_survey_revision_feedback_flow.py](../messaging/tests/test_survey_revision_feedback_flow.py) | 모든 단위 & E2E 테스트 |

---

## 라이선스

이 테스트 가이드는 landinghelp_server 프로젝트의 일부입니다.
