#!/usr/bin/env python
"""
설문 필드 변경 패턴 검증 테스트

사용 방법:
  python test_survey_field_pattern.py
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from customer_request_policy import classify_customer_request, Intent


def test_survey_field_recognition():
    """설문 필드명 기반으로 SURVEY_REOPEN_REQUEST를 정확히 인식하는지 확인"""
    
    test_cases = [
        # (customer_message, expected_intent, description)
        ("입국 인원이 바뀌어요", Intent.SURVEY_REOPEN_REQUEST, "필드명(입국) + 변경 표현"),
        ("입국 인원이 바꼈어요", Intent.SURVEY_REOPEN_REQUEST, "필드명(입국) + 변경 표현 오타 변형"),
        ("비자 타입을 잘못 입력했어요", Intent.SURVEY_REOPEN_REQUEST, "필드명(비자) + 오류 표현"),
        ("주거 지역을 수정할게요", Intent.SURVEY_REOPEN_REQUEST, "필드명(주거) + 수정"),
        ("이메일 주소를 변경하고 싶어요", Intent.SURVEY_REOPEN_REQUEST, "필드명(이메일) + 변경"),
        ("공항 선택을 다시 하고 싶어요", Intent.SURVEY_REOPEN_REQUEST, "필드명(공항) + 다시"),
        ("비행기 도착 시간이 변경됐어", Intent.SURVEY_REOPEN_REQUEST, "필드명(도착 시간/비행기) + 변경"),
        ("기간을 잘못 선택했어요", Intent.SURVEY_REOPEN_REQUEST, "필드명(기간) + 잘못"),
        
        # 기존 패턴 (설문 + 수정 키워드)
        ("설문을 수정하고 싶어요", Intent.SURVEY_REOPEN_REQUEST, "기존 설문+수정 패턴"),
        ("설문을 다시 작성할게요", Intent.SURVEY_REOPEN_REQUEST, "기존 설문+재작성 패턴"),
        
        # 서비스 변경 (기존 지원)
        ("서비스를 변경하고 싶어요", Intent.SURVEY_REOPEN_REQUEST, "서비스 변경 → 설문재수정"),
        
        # 일반 질문 (패턴 미매칭)
        ("언제 비용이 나오나요?", Intent.GENERAL_QUESTION, "일반 질문"),
        ("설문 작성은 어떻게 하나요?", Intent.GENERAL_QUESTION, "설문 프로세스 질문 (수정 신호 없음)"),
    ]
    
    print("=" * 80)
    print("설문 필드 패턴 검증 테스트")
    print("=" * 80)
    
    passed = 0
    failed = 0
    
    for message, expected_intent, description in test_cases:
        result = classify_customer_request(message, context={}, allow_llm=False)
        
        detected_intent = result.policy.detected_intent
        status = "✓ PASS" if detected_intent == expected_intent else "✗ FAIL"
        if detected_intent == expected_intent:
            passed += 1
        else:
            failed += 1
        
        print(f"\n{status}")
        print(f"  메시지: {message}")
        print(f"  설명: {description}")
        print(f"  기대값: {expected_intent.value}")
        print(f"  실제값: {detected_intent.value}")
        print(f"  신뢰도: {result.policy.confidence:.2f}")
        print(f"  사유: {result.policy.internal_reasoning_summary}")
        if result.policy.customer_facing_summary:
            print(f"  고객메시지: {result.policy.customer_facing_summary}")

    
    print("\n" + "=" * 80)
    print(f"결과: PASSED={passed}, FAILED={failed}")
    print("=" * 80)
    
    return failed == 0


if __name__ == "__main__":
    success = test_survey_field_recognition()
    exit(0 if success else 1)
