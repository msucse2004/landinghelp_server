"""
DeepL API가 auth key를 읽어 번역이 정상 동작하는지 확인합니다.
실행: python manage.py test_deepl_translation
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "DeepL API 키 로드 및 번역 동작 확인 (테스트 문장 1건 호출)"

    def handle(self, *args, **options):
        from django.conf import settings
        import os

        auth_key = (getattr(settings, "DEEPL_AUTH_KEY", None) or os.environ.get("DEEPL_AUTH_KEY") or "").strip()
        if not auth_key:
            self.stdout.write(self.style.ERROR("DEEPL_AUTH_KEY가 없습니다. 환경 변수 확인 후 다시 실행하세요."))
            return

        self.stdout.write("1) DEEPL_AUTH_KEY: 설정됨 (길이 %d)" % len(auth_key))

        from translations.services import _get_deepl_translator, _translate_one

        translator = _get_deepl_translator()
        if not translator:
            self.stdout.write(self.style.ERROR("2) DeepL Translator 초기화 실패. API 키가 유효한지 확인하세요."))
            return

        self.stdout.write(self.style.SUCCESS("2) DeepL Translator: 초기화 성공"))

        test_text = "안녕하세요"
        result = _translate_one(test_text, "en", "ko")
        if not result:
            self.stdout.write(self.style.ERROR("3) 번역 실패: '%s' -> (빈 결과)" % test_text))
            return

        self.stdout.write(self.style.SUCCESS("3) 번역 성공: '%s' -> '%s'" % (test_text, result)))
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("DeepL API가 정상 동작합니다."))
