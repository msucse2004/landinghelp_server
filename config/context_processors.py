# config: 템플릿 컨텍스트 프로세서

from django.conf import settings


def email_config_warning(request):
    """
    SMTP 백엔드 사용 시 EMAIL_HOST_USER, EMAIL_HOST_PASSWORD가 비어 있으면 경고 플래그 전달.
    """
    warning = False
    if 'smtp' in (getattr(settings, 'EMAIL_BACKEND', '') or '').lower():
        user = getattr(settings, 'EMAIL_HOST_USER', '') or ''
        password = getattr(settings, 'EMAIL_HOST_PASSWORD', '') or ''
        if not user.strip() or not password.strip():
            warning = True
    return {'email_config_warning': warning}
