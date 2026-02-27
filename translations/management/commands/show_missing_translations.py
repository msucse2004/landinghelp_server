"""
고정 번역(StaticTranslation) DB에서 빈 언어 컬럼이 있는 항목을 조회합니다.
결과를 터미널과(요약) 파일로 출력합니다.

  python manage.py show_missing_translations
  python manage.py show_missing_translations --out report.txt
"""
from django.core.management.base import BaseCommand

LANG_FIELDS = ['en', 'es', 'zh_hans', 'zh_hant', 'vi']


class Command(BaseCommand):
    help = '번역이 비어 있는 고정 번역 항목 조회 (요약 + 파일 출력)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--out',
            type=str,
            default='',
            metavar='FILE',
            help='결과를 저장할 파일 경로 (UTF-8). 비우면 출력 안 함.',
        )

    def handle(self, *args, **options):
        from translations.models import StaticTranslation

        total = StaticTranslation.objects.count()
        missing_list = []
        for row in StaticTranslation.objects.all().order_by('key'):
            empty = [f for f in LANG_FIELDS if not (getattr(row, f, None) or '').strip()]
            if empty:
                source = (row.ko or row.key or '').strip()
                missing_list.append((row.key, empty, source))

        self.stdout.write(self.style.SUCCESS(
            f'Total rows: {total} | Rows with missing translation(s): {len(missing_list)}'
        ))

        out_path = (options.get('out') or '').strip()
        if out_path:
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(f'Total rows: {total}\n')
                f.write(f'Rows with missing translation(s): {len(missing_list)}\n\n')
                for key, empty_langs, source in missing_list:
                    f.write(f'{key}\t{",".join(empty_langs)}\t{source}\n')
            self.stdout.write(self.style.SUCCESS(f'Written: {out_path}'))
        if missing_list and not out_path:
            self.stdout.write('Run with --out FILE to save full list (UTF-8).')
