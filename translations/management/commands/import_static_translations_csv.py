"""
프로젝트 루트의 static_translations_all.csv를 읽어 StaticTranslation에 반영합니다.
--fill-empty 시 CSV에서 비어 있는 언어 셀을 파이프라인(DeepL→Ollama)으로 채움. 재실행 시 이미 값 있는 항목 건너뜀.

  python manage.py import_static_translations_csv
  python manage.py import_static_translations_csv --path /path/to/file.csv
  python manage.py import_static_translations_csv --fill-empty   # 빈 셀만 파이프라인으로 채움
"""
import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from translations.models import StaticTranslation


# DB 필드명 → API/파이프라인용 언어 코드 (비어 있는 셀 채울 때 사용)
_FIELD_TO_LANG = {'en': 'en', 'es': 'es', 'zh_hans': 'zh-hans', 'zh_hant': 'zh-hant', 'vi': 'vi'}
_FILL_FIELDS = ['en', 'es', 'zh_hans', 'zh_hant', 'vi']


class Command(BaseCommand):
    help = 'CSV를 고정 번역 DB에 반영. --fill-empty 시 빈 셀을 파이프라인으로 채움(이미 있으면 건너뜀).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--path',
            type=str,
            default=None,
            help='CSV 파일 경로. 미지정 시 프로젝트 루트의 static_translations_all.csv 사용',
        )
        parser.add_argument(
            '--fill-empty',
            action='store_true',
            help='CSV 반영 후 비어 있는 언어 셀을 파이프라인(DeepL→Ollama)으로 채움. 이미 값 있으면 건너뜀.',
        )

    def handle(self, *args, **options):
        path = options.get('path')
        fill_empty = options.get('fill_empty', False)
        if path:
            csv_path = Path(path)
        else:
            csv_path = Path(settings.BASE_DIR) / 'static_translations_all.csv'
        if not csv_path.exists():
            self.stderr.write(self.style.ERROR(f'파일 없음: {csv_path}'))
            return
        created = updated = filled_count = 0
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

            if fill_empty:
                source_text = (obj.ko or obj.key or '').strip()
                if not source_text:
                    continue
                from translations.services import _translate_for_save
                from translations.utils import save_translation_from_api
                for field in _FILL_FIELDS:
                    val = (getattr(obj, field, None) or '').strip()
                    if val:
                        continue
                    lang_code = _FIELD_TO_LANG.get(field)
                    if not lang_code:
                        continue
                    translated = _translate_for_save(source_text, lang_code, 'ko')
                    if translated:
                        setattr(obj, field, translated)
                        obj.save(update_fields=[field])
                        filled_count += 1

        try:
            from translations.utils import invalidate_cache
            invalidate_cache()
            self.stdout.write('고정 번역 캐시를 초기화했습니다.')
        except Exception:
            pass
        msg = f'완료: 생성 {created}건, 갱신 {updated}건'
        if fill_empty and filled_count:
            msg += f', 빈 셀 채움(파이프라인) {filled_count}건'
        self.stdout.write(self.style.SUCCESS(msg))
