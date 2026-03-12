#!/usr/bin/env python
"""
실제 고객 메시지 예제 검증

스크린샷에서 캡처한 고객 메시지들이 정확히 분류되는지 확인
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from customer_request_policy import classify_customer_request, Intent


def test_real_customer_messages():
    """사용자가 공유한 스크린샷의 실제 고객 메시지들"""
    
    real_messages = [
        # 스크린샷의 메시지들
        ("입국 인원이 바뀌어요", Intent.SURVEY_REOPEN_REQUEST),
        ("입국 인원이 바꼈어요", Intent.SURVEY_REOPEN_REQUEST),
        ("비자 타입을 잘못 입력했어요", Intent.SURVEY_REOPEN_REQUEST),
        
        # 유사한 변형들 (같은 의도)
        ("입국 기간이 변경됐어요", Intent.SURVEY_REOPEN_REQUEST),
        ("주거 형태를 다시 선택하고 싶어요", Intent.SURVEY_REOPEN_REQUEST),
        ("이메일을 잘못 입력했네요", Intent.SURVEY_REOPEN_REQUEST),
        ("할당된 공항이 맞지 않아요", Intent.SURVEY_REOPEN_REQUEST),
        ("신청자 이름을 수정할게요", Intent.SURVEY_REOPEN_REQUEST),
        
        # 엣지 케이스
        ("아 입국 인원이 늘어났어요", Intent.SURVEY_REOPEN_REQUEST),  # "늘어났어" 변형
        ("비자 종류가 틀렸어요", Intent.SURVEY_REOPEN_REQUEST),  # "틀렸어"
        ("기간을 정정할 필요가 있어요", Intent.SURVEY_REOPEN_REQUEST),  # "정정"
    ]
    
    print("=" * 80)
    print("실제 고객 메시지 분류 검증")
    print("=" * 80)
    
    all_pass = True
    
    for message, expected_intent in real_messages:
        result = classify_customer_request(message, context={}, allow_llm=False)
        detected = result.policy.detected_intent
        
        is_pass = detected == expected_intent
        all_pass = all_pass and is_pass
        
        status = "✓" if is_pass else "✗"
        print(f"\n{status} {message}")
        print(f"   → 의도: {detected.value}")
        print(f"   → 신뢰도: {result.policy.confidence:.2f}")
        if result.policy.customer_facing_summary:
            print(f"   → 응답: {result.policy.customer_facing_summary[:70]}...")
    
    print("\n" + "=" * 80)
    print(f"결과: {'모두 성공 ✓' if all_pass else '실패가 있음 ✗'}")
    print("=" * 80)
    
    return all_pass


if __name__ == "__main__":
    success = test_real_customer_messages()
    exit(0 if success else 1)
