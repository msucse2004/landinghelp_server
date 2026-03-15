"""
번역 DB(StaticTranslation)의 영어(en) 컬럼에 표기 규칙을 적용합니다.
- 단어의 첫 글자 대문자 (공백·슬래시 구분 단어별 Title Case)
- 문장의 첫 글자 대문자 (. ! ? 뒤 새 문장 시작도 대문자)

  python manage.py normalize_english_in_db
  python manage.py normalize_english_in_db --dry-run  # 변경 예정만 출력
"""
from django.core.management.base import BaseCommand

from translations.models import StaticTranslation
from translations.utils import normalize_english_display, invalidate_cache


class Command(BaseCommand):
    help = '번역 DB의 en 컬럼에 영어 표기 규칙(단어·문장 첫 글자 대문자) 적용'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='저장하지 않고 변경 예정만 출력',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        updated = 0
        for row in StaticTranslation.objects.all().order_by('key'):
            current = (row.en or '').strip()
            if not current:
                continue
            normalized = normalize_english_display(current)
            if normalized != current:
                updated += 1
                if dry_run:
                    try:
                        self.stdout.write(f'  {row.key!r}: {current!r} -> {normalized!r}')
                    except UnicodeEncodeError:
                        self.stdout.write(f'  pk={row.pk}: en updated (unicode)')
                else:
                    row.en = normalized
                    row.save(update_fields=['en'])
        if dry_run:
            self.stdout.write(self.style.SUCCESS(f'Dry run: {updated} row(s) would be updated.'))
        else:
            invalidate_cache()
            self.stdout.write(self.style.SUCCESS(f'Updated {updated} row(s).'))
