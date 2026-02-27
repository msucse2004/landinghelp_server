"""이메일 환경변수 확인: python manage.py check_email_env"""
import os

from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, DEFAULT_FROM_EMAIL 환경변수 설정 여부 확인"

    def handle(self, *args, **options):
        user = os.environ.get('EMAIL_HOST_USER', '')
        password = os.environ.get('EMAIL_HOST_PASSWORD', '')
        from_email = os.environ.get('DEFAULT_FROM_EMAIL', '')

        self.stdout.write("=== 이메일 환경변수 확인 ===")
        self.stdout.write("EMAIL_BACKEND: %s" % settings.EMAIL_BACKEND)
        self.stdout.write("")
        self.stdout.write("EMAIL_HOST_USER: %s" % ("설정됨" if user and user.strip() else "미설정"))
        self.stdout.write("EMAIL_HOST_PASSWORD: %s" % ("설정됨" if password and password.strip() else "미설정"))
        self.stdout.write("DEFAULT_FROM_EMAIL: %s" % (from_email or "(미설정, 기본값 사용)"))
        self.stdout.write("")

        if 'smtp' in (settings.EMAIL_BACKEND or '').lower():
            if not (user and user.strip()) or not (password and password.strip()):
                self.stdout.write(self.style.WARNING(
                    "SMTP 사용 중이지만 EMAIL_HOST_USER 또는 EMAIL_HOST_PASSWORD가 비어 있습니다. "
                    "시스템 환경변수로 설정하세요. (run_local 실행 전 터미널에서 export 또는 set_email_env.ps1)"
                ))
            else:
                self.stdout.write(self.style.SUCCESS("이메일 환경변수 설정 완료."))
        else:
            self.stdout.write("Console 백엔드 사용 중 (환경변수 불필요)")
