"""
설문 제출(SurveySubmission) 상태 전이 로직.
뷰에서는 직접 status를 바꾸지 않고 이 모듈의 함수를 호출한다.
"""
from django.utils import timezone


def mark_submission_service_in_progress(submission) -> bool:
    """
    결제 완료 후 전담 Agent 배정 시: submission을 SERVICE_IN_PROGRESS로 전환.
    이미 SERVICE_IN_PROGRESS이면 no-op.
    Returns: True if updated, False if already in progress or no submission.
    """
    if not submission:
        return False
    from .models import SurveySubmission
    if getattr(submission, 'status', None) == SurveySubmission.Status.SERVICE_IN_PROGRESS:
        return False
    submission.status = SurveySubmission.Status.SERVICE_IN_PROGRESS
    submission.save(update_fields=['status', 'updated_at'])
    return True
