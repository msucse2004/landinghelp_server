# 선호 언어 DB 확인: python manage.py check_preferred_language [username]
from django.core.management.base import BaseCommand

from accounts.models import User


class Command(BaseCommand):
    help = "DB에서 지정 사용자(기본 a1)의 preferred_language 값을 조회합니다."

    def add_arguments(self, parser):
        parser.add_argument(
            "username",
            nargs="?",
            default="a1",
            help="확인할 사용자명 (기본: a1)",
        )

    def handle(self, *args, **options):
        username = options["username"]
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"사용자 '{username}' 없음."))
            return
        raw = getattr(user, "preferred_language", None)
        self.stdout.write(
            f"username={user.username} preferred_language={repr(raw)} (DB에서 직접 조회)"
        )
