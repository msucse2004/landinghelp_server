"""
고정 번역(StaticTranslation) DB의 빈 언어 컬럼을 DeepL로 번역해 채웁니다.
ko를 원문으로 en, es, zh_hans, zh_hant, vi 중 비어 있는 항목만 번역·저장합니다.

  python manage.py fill_translations_deepl
  python manage.py fill_translations_deepl --dry-run   # 번역 건수만 출력
  python manage.py fill_translations_deepl --force     # 이미 있는 값도 재번역
  python manage.py fill_translations_deepl --limit 10  # 처음 10건만 (테스트용)
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'DeepL로 고정 번역 DB의 빈 언어(en, es, zh_hans, zh_hant, vi)를 채웁니다.'

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

    def handle(self, *args, **options):
        import os
        dry_run = options.get('dry_run', False)
        force = options.get('force', False)
        limit = options.get('limit') or 0

        auth_key = (getattr(settings, 'DEEPL_AUTH_KEY', None) or os.environ.get('DEEPL_AUTH_KEY', '') or '').strip()
        if not auth_key:
            raise CommandError(
                'DEEPL_AUTH_KEY가 설정되지 않았습니다. '
                '환경변수 DEEPL_AUTH_KEY 또는 settings.DEEPL_AUTH_KEY를 설정하세요. '
                'https://www.deepl.com/pro-api 에서 API 키 발급.'
            )

        from translations.models import StaticTranslation
        from translations.utils import invalidate_cache
        from translations.services import _translate_one
        from translations.utils import get_supported_language_codes, save_translation_from_api

        invalidate_cache()
        qs = StaticTranslation.objects.all().order_by('key')
        if limit > 0:
            qs = qs[:limit]

        total_rows = 0
        total_filled = 0
        supported = get_supported_language_codes()
        target_langs = [l for l in supported if l != 'ko']
        lang_to_field = {'en': 'en', 'es': 'es', 'zh-hans': 'zh_hans', 'zh-hant': 'zh_hant', 'vi': 'vi'}

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

            for lang in target_langs:
                if not force:
                    f = lang_to_field.get(lang, lang)
                    if getattr(row, f, None) and str(getattr(row, f, '')).strip():
                        continue
                translated_text = _translate_one(source_text, lang, 'ko')
                if translated_text:
                    save_translation_from_api(row.key, lang, translated_text)
                    total_filled += 1

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f'대상 행: {total_rows}건, 채울 번역 수: {total_filled}개 (실행 안 함)'))
        else:
            invalidate_cache()
            self.stdout.write(self.style.SUCCESS(f'처리 행: {total_rows}건, 채운 번역: {total_filled}개'))
