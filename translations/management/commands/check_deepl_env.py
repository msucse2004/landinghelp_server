# DEEPL_AUTH_KEY가 Windows 환경 변수(및 Django 설정)에서 읽히는지 확인
# 실행: python manage.py check_deepl_env
# 키 값은 출력하지 않고, 설정 여부와 길이만 표시 (보안)
import os

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "DEEPL_AUTH_KEY가 환경 변수 및 settings에서 읽히는지 확인 (키 값은 출력하지 않음)"

    def handle(self, *args, **options):
        env_val = os.environ.get("DEEPL_AUTH_KEY", "")
        settings_val = getattr(settings, "DEEPL_AUTH_KEY", "") or ""

        env_set = bool((env_val or "").strip())
        settings_set = bool((settings_val or "").strip())

        self.stdout.write("--- DEEPL_AUTH_KEY 확인 ---")
        if env_set:
            self.stdout.write(
                self.style.SUCCESS(
                    f"  os.environ['DEEPL_AUTH_KEY']: 설정됨 (길이 {len(env_val.strip())})"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING("  os.environ['DEEPL_AUTH_KEY']: 없음")
            )

        if settings_set:
            self.stdout.write(
                self.style.SUCCESS(
                    f"  settings.DEEPL_AUTH_KEY: 설정됨 (길이 {len(str(settings_val).strip())})"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING("  settings.DEEPL_AUTH_KEY: 없음")
            )

        self.stdout.write("")
        if env_set and settings_set:
            self.stdout.write(
                self.style.SUCCESS("번역 API에서 사용 가능: 환경 변수에서 정상 로드됨.")
            )
        elif settings_set and not env_set:
            self.stdout.write(
                self.style.WARNING(
                    "settings에는 있으나 os.environ에는 없음. "
                    "(.env 등으로 로드된 경우. 웹 요청 시 동일 프로세스면 사용 가능)"
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(
                    "DEEPL_AUTH_KEY가 없습니다. "
                    "Windows: 시스템 속성 → 고급 → 환경 변수에서 DEEPL_AUTH_KEY 추가 후, "
                    "터미널/IDE를 다시 실행하세요."
                )
            )
