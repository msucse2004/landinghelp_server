"""
번역 DB(StaticTranslation)에 지정한 키가 있는지, 각 언어별 값이 채워져 있는지 확인합니다.
팝업에 나온 "Failed keys"가 DB에 실제로 없는지 검증할 때 사용.

  python manage.py check_translation_keys
  python manage.py check_translation_keys "고객 예약 달력" "미설정"
"""
from django.core.management.base import BaseCommand

from translations.models import StaticTranslation, LANG_CODE_TO_FIELD


class Command(BaseCommand):
    help = '번역 DB에서 지정 키의 언어별 저장 여부 확인 (실제 번역 실패 여부 검증)'

    def add_arguments(self, parser):
        parser.add_argument(
            'keys',
            nargs='*',
            help='확인할 키(공백 구분). 비우면 예시 키 몇 개로 확인.',
        )

    def handle(self, *args, **options):
        keys = [k.strip() for k in (options.get('keys') or []) if k and k.strip()]
        if not keys:
            keys = [
                '고객 예약 달력',
                '고객이 신청한 약속을 날짜별로 확인하고, 수락하거나 메시지를 보낼 수 있습니다.',
                '미설정',
                '에이전트 계정입니다.',
            ]
        self.stdout.write('StaticTranslation DB check (key -> per-language value)')
        self.stdout.write('=' * 60)
        for key in keys:
            self._check_key(key)
        self.stdout.write('=' * 60)
        self.stdout.write('Empty or Korean-only value = treated as "translation failed" for that language.')

    def _check_key(self, key):
        try:
            row = StaticTranslation.objects.get(key=key)
        except StaticTranslation.DoesNotExist:
            self.stdout.write(self.style.WARNING(f'\n[NOT IN DB] {key!r}'))
            self.stdout.write('  -> No row. API was tried and failed to save.')
            return
        self.stdout.write(f'\n[IN DB] {key!r}')
        for lang_code, field in LANG_CODE_TO_FIELD.items():
            val = (getattr(row, field, None) or '').strip()
            if not val:
                status = self.style.WARNING('(empty)')
            elif any('\uac00' <= c <= '\ud7a3' for c in val):
                status = self.style.NOTICE('(Korean only) -> fails for non-ko request')
            else:
                preview = (val[:50] + '...') if len(val) > 50 else val
                status = self.style.SUCCESS(preview)
            self.stdout.write(f'  {lang_code}: {status}')
