"""
번역 DB(StaticTranslation)에서 비어 있는 언어 컬럼을 파이프라인(DeepL→Ollama)으로 채운 뒤,
여전히 비어 있거나 한글만 있는 항목(번역 실패)을 키별로 리스트업합니다.
재실행 시 이미 번역된 항목은 건너뜀 (--force 시에만 재번역). placeholder 보호·UI 톤 유지.

  python manage.py fill_translations_and_list_failed
  python manage.py fill_translations_and_list_failed --dry-run   # 채우기만 시뮬레이션 후 실패 목록
  python manage.py fill_translations_and_list_failed --limit 50  # 처음 50행만 채우기
  python manage.py fill_translations_and_list_failed --out failed.txt  # 실패 목록을 파일로 저장
"""
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def _is_empty_or_korean_only(val):
    if not val or not str(val).strip():
        return True
    s = str(val).strip()
    return any('\uac00' <= c <= '\ud7a3' for c in s)


class Command(BaseCommand):
    help = '파이프라인(DeepL→Ollama)으로 빈 번역을 채운 뒤 실패한 키 목록 출력. 재실행 시 이미 있는 항목 건너뜀.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='실제 번역/저장 없이, 현재 기준 실패 목록만 출력',
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
            help='채울 행 수 제한 (0=전체)',
        )
        parser.add_argument(
            '--out',
            type=str,
            default='',
            metavar='FILE',
            help='번역 실패 목록을 저장할 파일 경로 (UTF-8)',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        force = options.get('force', False)
        limit = options.get('limit') or 0
        out_path = (options.get('out') or '').strip()

        auth_key = (
            getattr(settings, 'DEEPL_AUTH_KEY', None)
            or os.environ.get('DEEPL_AUTH_KEY', '')
            or ''
        ).strip()
        if not auth_key and not dry_run:
            raise CommandError(
                'DEEPL_AUTH_KEY가 설정되지 않았습니다. '
                '환경변수 DEEPL_AUTH_KEY 또는 settings.DEEPL_AUTH_KEY를 설정하세요.'
            )

        from translations.models import StaticTranslation, LANG_CODE_TO_FIELD
        from translations.utils import invalidate_cache, get_supported_language_codes
        from translations.services import _translate_for_save
        from translations.utils import save_translation_from_api

        invalidate_cache()
        qs = StaticTranslation.objects.all().order_by('key')
        if limit > 0:
            qs = qs[:limit]

        supported = get_supported_language_codes()
        target_langs = [l for l in supported if l != 'ko']
        lang_to_field = {'en': 'en', 'es': 'es', 'zh-hans': 'zh_hans', 'zh-hant': 'zh_hant', 'vi': 'vi'}

        total_rows = 0
        total_filled = 0

        if not dry_run:
            self.stdout.write('Filling empty translations with DeepL...')
            for row in qs:
                source_text = (row.ko or row.key or '').strip()
                if not source_text:
                    continue
                total_rows += 1
                for lang in target_langs:
                    f = lang_to_field.get(lang, lang)
                    val = getattr(row, f, None) if hasattr(row, f) else None
                    if not force and (val and str(val).strip() and not _is_empty_or_korean_only(val)):
                        continue
                    translated_text = _translate_for_save(source_text, lang, 'ko')
                    if translated_text and not _is_empty_or_korean_only(translated_text):
                        save_translation_from_api(row.key, lang, translated_text)
                        total_filled += 1
            invalidate_cache()
            self.stdout.write(self.style.SUCCESS(f'Filled {total_filled} translation(s) from {total_rows} row(s).'))
        else:
            total_rows = qs.count()
            self.stdout.write(f'Dry run: not saving. Row count: {total_rows}')

        # Reload and list keys that still have empty or Korean-only for any non-ko language
        self.stdout.write('')
        self.stdout.write('Listing keys that still have missing or Korean-only translation (failed):')
        self.stdout.write('=' * 60)

        failed_list = []
        for row in StaticTranslation.objects.all().order_by('key'):
            key = (row.key or '').strip()
            if not key:
                continue
            missing_langs = []
            for lang in target_langs:
                field = LANG_CODE_TO_FIELD.get(lang)
                if not field:
                    continue
                val = (getattr(row, field, None) or '').strip()
                if _is_empty_or_korean_only(val):
                    missing_langs.append(lang)
            if missing_langs:
                failed_list.append((key, missing_langs))

        for key, missing_langs in failed_list:
            self.stdout.write(f'  {key}')
            self.stdout.write(self.style.WARNING(f'    -> missing or invalid: {", ".join(missing_langs)}'))

        self.stdout.write('=' * 60)
        self.stdout.write(self.style.SUCCESS(f'Total keys with failed translation: {len(failed_list)}'))

        if out_path:
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write('key\tmissing_languages\n')
                for key, missing_langs in failed_list:
                    f.write(f'{key}\t{",".join(missing_langs)}\n')
            self.stdout.write(self.style.SUCCESS(f'Written: {out_path}'))
