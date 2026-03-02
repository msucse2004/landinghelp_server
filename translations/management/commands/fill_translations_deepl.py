"""
고정 번역(StaticTranslation) DB의 빈 언어 컬럼을 파이프라인(DeepL→Ollama)으로 채웁니다.
UI 톤·placeholder 보호 유지. 재실행 시 이미 번역된 항목은 건너뜀 (--force 시에만 재번역).

  python manage.py fill_translations_deepl
  python manage.py fill_translations_deepl --dry-run   # 번역 건수만 출력
  python manage.py fill_translations_deepl --force     # 이미 있는 값도 재번역
  python manage.py fill_translations_deepl --limit 10  # 처음 10건만 (테스트용)
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = '파이프라인(DeepL→Ollama)으로 고정 번역 DB의 빈 언어를 채움. 재실행 시 이미 있는 항목은 건너뜀.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='실제 번역/저장 없이 대상 건수만 출력',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='이미 값이 있는 언어도 다시 번역해 덮어쓰기',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            metavar='N',
            help='처리할 행 수 제한 (0=전체). 테스트용.',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='행 단위 진행 상황 출력',
        )

    def handle(self, *args, **options):
        import os
        dry_run = options.get('dry_run', False)
        force = options.get('force', False)
        limit = options.get('limit') or 0
        verbose = options.get('verbose', False)

        auth_key = (getattr(settings, 'DEEPL_AUTH_KEY', None) or os.environ.get('DEEPL_AUTH_KEY', '') or '').strip()
        if not auth_key:
            raise CommandError(
                'DEEPL_AUTH_KEY가 설정되지 않았습니다. '
                '환경변수 DEEPL_AUTH_KEY 또는 settings.DEEPL_AUTH_KEY를 설정하세요. '
                'https://www.deepl.com/pro-api 에서 API 키 발급.'
            )

        from translations.models import StaticTranslation
        from translations.utils import invalidate_cache
        from translations.services import _translate_for_save
        from translations.utils import get_supported_language_codes, save_translation_from_api

        invalidate_cache()
        qs = StaticTranslation.objects.all().order_by('key')
        total_expected = limit if limit > 0 else qs.count()
        if limit > 0:
            qs = qs[:limit]

        total_rows = 0
        total_filled = 0
        supported = get_supported_language_codes()
        target_langs = [l for l in supported if l != 'ko']
        lang_to_field = {'en': 'en', 'es': 'es', 'zh-hans': 'zh_hans', 'zh-hant': 'zh_hant', 'vi': 'vi'}

        if verbose and not dry_run:
            self.stdout.write(
                f'[Full check] Pipeline (DeepL->LLM) started. ~{total_expected} rows x {len(target_langs)} langs'
            )
            self.stdout.write('---')
            if hasattr(self.stdout, 'flush'):
                self.stdout.flush()

        for row in qs:
            source_text = (row.ko or row.key or '').strip()
            if not source_text:
                continue
            total_rows += 1
            if dry_run:
                for lang in target_langs:
                    f = lang_to_field.get(lang, lang)
                    val = getattr(row, f, None) if hasattr(row, f) else None
                    if force or not (val and str(val).strip()):
                        total_filled += 1
                continue

            row_filled = 0
            for lang in target_langs:
                if not force:
                    f = lang_to_field.get(lang, lang)
                    if getattr(row, f, None) and str(getattr(row, f, '')).strip():
                        continue
                translated_text = _translate_for_save(source_text, lang, 'ko')
                if translated_text:
                    save_translation_from_api(row.key, lang, translated_text)
                    total_filled += 1
                    row_filled += 1
            if verbose and row_filled > 0:
                try:
                    self.stdout.write(
                        f'  [OK] row {total_rows}/{total_expected}: +{row_filled} (total {total_filled})'
                    )
                    if hasattr(self.stdout, 'flush'):
                        self.stdout.flush()
                except UnicodeEncodeError:
                    pass

        if dry_run:
            try:
                self.stdout.write(self.style.SUCCESS(f'Rows: {total_rows}, to fill: {total_filled} (dry-run)'))
            except UnicodeEncodeError:
                self.stdout.write(self.style.SUCCESS(f'Done. Rows={total_rows}, to_fill={total_filled}'))
        else:
            invalidate_cache()
            try:
                self.stdout.write(self.style.SUCCESS(f'Done. Rows: {total_rows}, filled: {total_filled}'))
            except UnicodeEncodeError:
                self.stdout.write(self.style.SUCCESS(f'Done. Rows={total_rows} Filled={total_filled}'))
