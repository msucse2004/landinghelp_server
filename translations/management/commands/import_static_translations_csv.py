"""
프로젝트 루트의 static_translations_all.csv를 읽어 StaticTranslation에 반영합니다.
  python manage.py import_static_translations_csv
  python manage.py import_static_translations_csv --path /path/to/file.csv
"""
import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from translations.models import StaticTranslation


class Command(BaseCommand):
    help = 'CSV 파일(key, ko, en, es, zh-hans, zh-hant, vi)을 읽어 고정 번역 DB에 반영합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--path',
            type=str,
            default=None,
            help='CSV 파일 경로. 미지정 시 프로젝트 루트의 static_translations_all.csv 사용',
        )

    def handle(self, *args, **options):
        path = options.get('path')
        if path:
            csv_path = Path(path)
        else:
            csv_path = Path(settings.BASE_DIR) / 'static_translations_all.csv'
        if not csv_path.exists():
            self.stderr.write(self.style.ERROR(f'파일 없음: {csv_path}'))
            return
        created = updated = 0
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            self.stderr.write(self.style.WARNING('CSV에 행이 없습니다.'))
            return
        # 헤더: key, ko, en, es, zh-hans, zh-hant, vi
        header = [str(c).strip().lower() for c in rows[0]]
        if header and header[0] == 'key':
            rows = rows[1:]
        idx_key, idx_ko, idx_en, idx_es, idx_zh_hans, idx_zh_hant, idx_vi = 0, 1, 2, 3, 4, 5, 6
        for row in rows:
            if len(row) < 1:
                continue
            key = (row[idx_key] or '').strip()
            if not key:
                continue

            def cell(i):
                return (row[i] or '').strip() if i < len(row) else ''

            obj, created_ = StaticTranslation.objects.update_or_create(
                key=key,
                defaults={
                    'ko': cell(idx_ko),
                    'en': cell(idx_en),
                    'es': cell(idx_es),
                    'zh_hans': cell(idx_zh_hans),
                    'zh_hant': cell(idx_zh_hant),
                    'vi': cell(idx_vi),
                },
            )
            if created_:
                created += 1
            else:
                updated += 1
        try:
            from translations.utils import invalidate_cache
            invalidate_cache()
            self.stdout.write('고정 번역 캐시를 초기화했습니다.')
        except Exception:
            pass
        self.stdout.write(
            self.style.SUCCESS(f'완료: 생성 {created}건, 갱신 {updated}건')
        )
