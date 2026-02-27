"""이메일 설정 테스트: python manage.py send_test_email your@email.com"""
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings


class Command(BaseCommand):
    help = "SMTP 설정 테스트 - 수신 이메일 주소를 인자로 받음"

    def add_arguments(self, parser):
        parser.add_argument("email", type=str, help="테스트 메일 수신 주소")

    def handle(self, *args, **options):
        email = options["email"]
        self.stdout.write("설정 확인: BACKEND=%s" % settings.EMAIL_BACKEND)
        try:
            send_mail(
                "[테스트] 랜딩헬프 이메일 설정 확인",
                "이 메일이 보인다면 SMTP 설정이 정상입니다.",
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
            self.stdout.write(self.style.SUCCESS(f"성공: {email} 로 메일 발송 완료. 수신함/스팸함을 확인하세요."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"실패: {e}"))
