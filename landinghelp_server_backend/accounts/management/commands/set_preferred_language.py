# 선호 언어 설정: python manage.py set_preferred_language <username> <language_code>
from django.core.management.base import BaseCommand

from accounts.models import User
from translations.utils import get_valid_language_codes


class Command(BaseCommand):
    help = "DB에서 지정 사용자의 preferred_language를 설정합니다. (예: set_preferred_language a1 en)"

    def add_arguments(self, parser):
        parser.add_argument("username", help="사용자명 (예: a1)")
        parser.add_argument(
            "language_code",
            help="언어 코드 (예: en, ko, vi, es, zh-hans, zh-hant)",
        )

    def handle(self, *args, **options):
        username = options["username"]
        lang = (options["language_code"] or "").strip()
        valid = get_valid_language_codes()
        if lang not in valid:
            self.stdout.write(
                self.style.ERROR(f"유효하지 않은 언어 코드: {lang}. 사용 가능: {valid}")
            )
            return
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"사용자 '{username}' 없음."))
            return
        old = getattr(user, "preferred_language", None) or ""
        user.preferred_language = lang
        user.save(update_fields=["preferred_language"])
        self.stdout.write(
            self.style.SUCCESS(
                f"username={user.username} preferred_language: {repr(old)} -> {repr(lang)}"
            )
        )
