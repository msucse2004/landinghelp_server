# 설문 필드명 기반 분류 개선 (Survey Field-based Classification Enhancement)

## 문제점
고객이 설문 필드를 구체적으로 언급하며 수정을 요청해도 시스템이 `GENERAL_QUESTION`으로 분류하는 경우:

```
고객 메시지: "입국 인원이 바뀌어요"
→ 기존: GENERAL_QUESTION (0.45 신뢰도)
→ 요청됨: SURVEY_REOPEN_REQUEST (설문 재수정 필요)

고객 메시지: "비자 타입을 잘못 입력했어요"
→ 기존: GENERAL_QUESTION (0.45 신뢰도)
→ 요청됨: SURVEY_REOPEN_REQUEST (설문 재수정 필요)
```

## 해결책

### 1. 새로운 휴리스틱 패턴 추가
`customer_request_policy.py`에 **`_RE_SURVEY_FIELD_CHANGE`** 패턴 추가:

```python
_RE_SURVEY_FIELD_CHANGE = re.compile(
    r"(입국|인원|기간|비자|주거|지역|공항|도시|이름|성명|신청자|이메일|전화|주소|여권|가구|서비스|지원|성).*"
    r"(바뀌|바꿔|바꾸|잘못|틀렸|다시|수정|변경|편집|정정|수정할|고쳐|정정할)|"
    r"(바뀌|바꿔|바꾸|잘못|틀렸|다시|수정|변경|편집|정정|수정할|고쳐|정정할).*"
    r"(입국|인원|기간|비자|주거|지역|공항|도시|이름|성명|신청자|이메일|전화|주소|여권|가구|서비스|지원|성)",
    re.I,
)
```

**인식되는 설문 필드들:**
- 입국 관련: 입국, 인원, 기간, 비자
- 거주 관련: 주거, 지역, 공항, 도시
- 신청자 정보: 이름, 성명, 신청자, 이메일, 전화, 주소
- 기타: 여권, 가구, 서비스

**인식되는 변경 표현:**
- 바뀌, 바꿔, 바꾸 (changed/want to change)
- 잘못, 틀렸 (wrong/incorrect)
- 다시, 수정, 변경, 편집 (re-, modify, change, edit)
- 정정, 고쳐, 고쳐야 (correct/fix)

### 2. 휴리스틱 테이블에 패턴 통합
`_HEURISTIC_PATTERNS` 튜플에 새 항목 추가 (우선순위 3번):

```python
(_RE_SURVEY_FIELD_CHANGE, Intent.SURVEY_REOPEN_REQUEST, 0.70,
 "설문에 입력하신 정보 중 변경이 필요하신 항목이 있으신 것 같은데, 설문을 다시 수정해드릴까요?",
 "matched survey field change keywords (입국, 비자, 주거 등)"),
```

**신뢰도 점수:**
- 설문 필드명 + 변경 표현 = **0.70** (중정도 신뢰)
- (설문 + 수정 명시 = 0.75, 서비스 변경 = 0.70)

## 검증 결과

### 테스트 작성
파일: `test_survey_field_pattern.py`

### 테스트 결과: **11/11 PASS**

| 메시지 | 의도 | 신뢰도 | 상태 |
|--------|------|--------|------|
| 입국 인원이 바뀌어요 | SURVEY_REOPEN_REQUEST | 0.70 | ✓ |
| 비자 타입을 잘못 입력했어요 | SURVEY_REOPEN_REQUEST | 0.70 | ✓ |
| 주거 지역을 수정할게요 | SURVEY_REOPEN_REQUEST | 0.70 | ✓ |
| 이메일 주소를 변경하고 싶어요 | SURVEY_REOPEN_REQUEST | 0.70 | ✓ |
| 공항 선택을 다시 하고 싶어요 | SURVEY_REOPEN_REQUEST | 0.70 | ✓ |
| 기간을 잘못 선택했어요 | SURVEY_REOPEN_REQUEST | 0.70 | ✓ |
| 설문을 수정하고 싶어요 (기존 패턴) | SURVEY_REOPEN_REQUEST | 0.75 | ✓ |
| 설문을 다시 작성할게요 (기존 패턴) | SURVEY_REOPEN_REQUEST | 0.75 | ✓ |
| 서비스를 변경하고 싶어요 | SURVEY_REOPEN_REQUEST | 0.70 | ✓ |
| 언제 비용이 나오나요? (일반 질문) | GENERAL_QUESTION | 0.45 | ✓ |
| 설문 작성은 어떻게 하나요? | GENERAL_QUESTION | 0.45 | ✓ |

### E2E 회귀 테스트: **19/19 PASS**
기존 test_survey_revision_feedback_flow 테스트 모두 통과

## 처리 흐름

```
고객 메시지: "비자 타입을 잘못 입력했어요"
    ↓
_heuristic_policy() 실행
    ↓
패턴 매칭 시도:
  1. _RE_SURVEY_RESUME: ❌ (링크/이어 키워드 없음)
  2. _RE_SURVEY_REOPEN: ❌ (설문 메타 키워드 없음)
  3. _RE_SURVEY_FIELD_CHANGE: ✓ (비자 + 잘못)
    ↓
Intent.SURVEY_REOPEN_REQUEST 반환
신뢰도: 0.70
고객메시지: "설문에 입력하신 정보 중 변경이 필요하신 항목이 있으신 것 같은데, 설문을 다시 수정해드릴까요?"
    ↓
ActionOffer 생성 → 고객에게 제시
```

## 부작용 검사

### ✓ 기존 패턴 우선순위 유지
패턴 순서 (우선순위):
1. SURVEY_RESUME (이어하기) - 0.75
2. SURVEY_REOPEN (설문 수정 명시) - 0.75
3. **SURVEY_FIELD_CHANGE (필드명만)** - 0.70 ← NEW
4. SERVICE_CHANGE (서비스 변경) - 0.70
5. 기타 패턴들...

더 구체적인 신호("설문" 키워드)가 더 높은 신뢰도를 가지므로 기존 동작 유지 ✓

### ✓ 거짓 양성 최소화
패턴이 설문 필드명 + 변경 표현의 명확한 조합만 매칭하므로
단순히 필드명을 언급하는 것만으로는 감지되지 않음 ✓

## 다음 단계 (선택사항)

### 1. 필드명 한정 강화
특정 필드 문맥만 감지 (예: "이름 변경" = 신청자 정보, "비자 변경" = 설문 필드):
```python
# 더 구체적인 서브패턴
_RE_VISA_CHANGE = re.compile(r"비자.*(바뀌|변경|잘못|...)", re.I)  # 신뢰도 0.75
_RE_ENTRY_CHANGE = re.compile(r"(입국|인원).*(바뀌|변경|...)", re.I)  # 신뢰도 0.75
```

### 2. LLM 프롬프트 개선
Ollama/Gemini에서 설문 필드 변경을 "implicit survey modification" 신호로 인식:
```
"다음은 설문 필드 변경 요청의 예들입니다:
- '입국 인원이 바뀌어요' → SURVEY_REOPEN_REQUEST
- '비자 타입을 잘못 입력했어요' → SURVEY_REOPEN_REQUEST
이런 경우들은 고객이 기존 설문 답변을 수정하고 싶은 신호입니다."
```

### 3. A/B 테스트
신뢰도 임계값 조정 (0.70 → 0.65/0.75) 후 실제 사용자 상호작용 데이터로 효과 측정

### 4. 문맥 기반 강화
고객의 LandingHelp 계정에 이미 제출된 설문이 있으면 신뢰도 상향:
```python
if context.get("has_submitted_survey") and pattern_match:
    confidence = 0.75  # up from 0.70
```

## 파일 변경 사항

### customer_request_policy.py
- **라인 476-485**: `_RE_SURVEY_FIELD_CHANGE` 패턴 정의 추가
- **라인 520-523**: `_HEURISTIC_PATTERNS` 튜플에 패턴 항목 추가

### test_survey_field_pattern.py (신규)
- 11개 테스트 케이스로 필드명 기반 분류 검증
- 기존 패턴과 충돌 검사
- 일반 질문과의 구분 검증

## 요약
✅ **문제 해결**: "입국 인원", "비자 타입" 같은 필드명만으로도 SURVEY_REOPEN_REQUEST 인식
✅ **신뢰도**: 0.70 (합리적 수준, LLM 활용 가능)
✅ **호환성**: 기존 19개 E2E 테스트 모두 통과
✅ **확장성**: 필드명/변경표현 추가 시 쉬운 유지보수
