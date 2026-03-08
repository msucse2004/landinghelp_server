"""이메일 환경변수 확인: python manage.py check_email_env
환경변수 유무와 SMTP 연결(가능 시)을 체크합니다. 키/비밀은 코드·깃에 넣지 말고 환경변수로만 전달하세요.
"""
import os
import smtplib

from django.core.management.base import BaseCommand
from django.conf import settings


def _check_smtp_connection():
    """EMAIL_HOST 등이 설정된 경우 SMTP 포트 연결 시도. 성공 여부만 반환."""
    host = (getattr(settings, 'EMAIL_HOST', None) or '').strip()
    port = getattr(settings, 'EMAIL_PORT', 587)
    use_tls = getattr(settings, 'EMAIL_USE_TLS', True)
    if not host:
        return None  # 스킵
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 587
    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            if use_tls:
                smtp.starttls()
            # 로그인은 하지 않고 연결만 확인 (일부 서버는 연결만 해도 OK)
            smtp.noop()
        return True
    except Exception as e:
        return False


class Command(BaseCommand):
    help = "이메일 환경변수 유무 및 SMTP 연결(가능 시) 확인. 키/비밀은 환경변수로만 설정."

    def handle(self, *args, **options):
        user = (os.environ.get('EMAIL_HOST_USER') or '').strip()
        password = (os.environ.get('EMAIL_HOST_PASSWORD') or '').strip()
        from_email = (os.environ.get('DEFAULT_FROM_EMAIL') or '').strip()
        backend = settings.EMAIL_BACKEND or ''

        self.stdout.write("=== 이메일 환경변수 확인 ===")
        self.stdout.write("EMAIL_BACKEND: %s" % backend)
        self.stdout.write("EMAIL_HOST: %s" % (getattr(settings, 'EMAIL_HOST', '') or "(미설정)"))
        self.stdout.write("EMAIL_PORT: %s" % getattr(settings, 'EMAIL_PORT', 587))
        self.stdout.write("EMAIL_HOST_USER: %s" % ("설정됨" if user else "미설정"))
        self.stdout.write("EMAIL_HOST_PASSWORD: %s" % ("설정됨" if password else "미설정"))
        self.stdout.write("DEFAULT_FROM_EMAIL: %s" % (from_email or "(미설정, 기본값 사용)"))
        self.stdout.write("")

        if 'smtp' in backend.lower():
            if not user or not password:
                self.stdout.write(self.style.WARNING(
                    "SMTP 백엔드이지만 EMAIL_HOST_USER 또는 EMAIL_HOST_PASSWORD가 비어 있습니다. "
                    "환경변수로만 설정하세요. (.env는 gitignore, 코드/깃에 비밀 넣지 말 것)"
                ))
            else:
                self.stdout.write(self.style.SUCCESS("이메일 환경변수 설정됨."))
                # SMTP 연결 체크 (가능하면)
                conn = _check_smtp_connection()
                if conn is True:
                    self.stdout.write(self.style.SUCCESS("SMTP 연결: 성공"))
                elif conn is False:
                    self.stdout.write(self.style.WARNING(
                        "SMTP 연결: 실패 (호스트/포트/방화벽 또는 인증 정책 확인)"
                    ))
        else:
            self.stdout.write("Console 백엔드 사용 중 (실제 발송 없음, 리마인더 등 비활성)")
