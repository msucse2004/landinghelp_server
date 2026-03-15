# config: 에러 리포팅 시 민감 정보 숨김

import re

from django.utils.regex_helper import _lazy_re_compile
from django.views.debug import SafeExceptionReporterFilter


class SensitiveDataExceptionFilter(SafeExceptionReporterFilter):
    """
    이메일 등 민감 설정값을 에러 페이지/로그에서 숨김.
    """
    hidden_settings = _lazy_re_compile(
        "API|AUTH|TOKEN|KEY|SECRET|PASS|SIGNATURE|HTTP_COOKIE|"
        "EMAIL_HOST_USER|EMAIL_HOST_PASSWORD|DEFAULT_FROM_EMAIL",
        flags=re.I,
    )
