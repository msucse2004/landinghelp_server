"""
.po 파일의 빈 msgstr을 DeepL API로 자동 번역합니다.
메시지나 Admin에 항목을 추가한 뒤 makemessages로 .po를 갱신한 다음 이 명령을 실행하세요.

사용법:
  export DEEPL_AUTH_KEY=your_key   # 또는 .env에 설정
  python manage.py makemessages -l en -l zh_Hans -l zh_Hant -l vi -l es
  python manage.py translate_po

옵션:
  --locale en         특정 로케일만 번역 (예: en, zh_Hans)
  --force             이미 번역된 msgstr도 다시 번역
  --dry-run           API 호출만 하고 .po 파일은 수정하지 않음
"""
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


# Django locale 디렉터리 이름 -> DeepL API 언어 코드
LOCALE_TO_DEEPL = {
    'en': 'EN',
    'zh_hans': 'ZH-HANS',
    'zh_hant': 'ZH-HANT',
    'vi': 'VI',
    'es': 'ES',
}
# locale 디렉터리 이름 -> settings.LANGUAGES 언어 코드 (CSV/캐시용)
LOCALE_TO_LANG = {
    'en': 'en',
    'zh_hans': 'zh-hans',
    'zh_hant': 'zh-hant',
    'vi': 'vi',
    'es': 'es',
}
# 소스 언어 (LANGUAGE_CODE 기준)
SOURCE_DEEPL = 'KO'


def get_translator():
    """DeepL 번역기 인스턴스. API 키가 없으면 None."""
    auth_key = getattr(settings, 'DEEPL_AUTH_KEY', None) or os.environ.get('DEEPL_AUTH_KEY', '')
    if not auth_key:
        return None
    try:
        import deepl
        return deepl.Translator(auth_key)
    except Exception as e:
        raise CommandError(f'DeepL 초기화 실패: {e}')


def translate_text(translator, text: str, target_lang: str, source_lang: str = SOURCE_DEEPL) -> str:
    """한 줄 번역. placeholder(%(...)s)는 유지됩니다."""
    if not text or not text.strip():
        return text
    try:
        result = translator.translate_text(
            text,
            source_lang=source_lang,
            target_lang=target_lang,
            preserve_formatting=True,
        )
        return result.text
    except Exception as e:
        return ''


def run_translate_po(locales=None, force=False, dry_run=False):
    import polib

    try:
        from translations.utils import get_from_cache, save_translation_from_api
        from translations.services import get_or_translate_with_deepl
    except ImportError:
        get_from_cache = save_translation_from_api = get_or_translate_with_deepl = None

    translator = get_translator()
    if not translator:
        raise CommandError(
            'DEEPL_AUTH_KEY가 설정되지 않았습니다. '
            '환경변수 또는 settings.DEEPL_AUTH_KEY를 설정하세요. '
            'https://www.deepl.com/pro-api 에서 API 키 발급 가능(무료 tier 50만자/월).'
        )

    locale_paths = getattr(settings, 'LOCALE_PATHS', None)
    if not locale_paths:
        raise CommandError('settings.LOCALE_PATHS가 비어 있습니다.')

    base_path = Path(locale_paths[0]).resolve()
    if not base_path.exists():
        raise CommandError(f'locale 경로가 없습니다: {base_path}')

    # 대상 로케일: LOCALE_TO_DEEPL에 있는 디렉터리만
    if locales:
        target_locales = [loc.replace('-', '_').lower() for loc in locales]
    else:
        target_locales = [d.name for d in base_path.iterdir() if d.is_dir() and d.name.lower() in LOCALE_TO_DEEPL]

    total_translated = 0
    for loc in target_locales:
        deepl_code = LOCALE_TO_DEEPL.get(loc.lower())
        if not deepl_code:
            continue
        po_path = base_path / loc / 'LC_MESSAGES' / 'django.po'
        if not po_path.exists():
            continue

        po = polib.pofile(str(po_path))
        count = 0
        for entry in po:
            if not entry.msgid:
                continue
            if entry.obsolete:
                continue
            need_translate = force or not (entry.msgstr and entry.msgstr.strip())
            if not need_translate:
                continue
            target_lang = LOCALE_TO_LANG.get(loc)
            # DB 저장 시 파이프라인(DeepL→Ollama) 사용; 캐시 있으면 재번역 없이 사용
            if target_lang and get_or_translate_with_deepl:
                translated = get_or_translate_with_deepl(entry.msgid, target_lang)
            else:
                translated = translate_text(translator, entry.msgid, deepl_code)
            if translated:
                if not dry_run:
                    entry.msgstr = translated
                count += 1
            # 복수형 msgstr[0], msgstr[1] 등
            if entry.msgid_plural and entry.msgstr_plural:
                for idx, msgstr in entry.msgstr_plural.items():
                    if force or not (msgstr and msgstr.strip()):
                        to_translate = entry.msgid_plural if int(idx) else entry.msgid
                        if target_lang and get_or_translate_with_deepl:
                            t = get_or_translate_with_deepl(to_translate, target_lang)
                        else:
                            t = translate_text(translator, to_translate, deepl_code)
                        if t and not dry_run:
                            entry.msgstr_plural[idx] = t
                        if t:
                            count += 1

        if count and not dry_run:
            po.save()
        total_translated += count
        yield loc, deepl_code, count


class Command(BaseCommand):
    help = 'locale/*/LC_MESSAGES/django.po의 빈 msgstr을 DeepL API로 자동 번역합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--locale',
            action='append',
            dest='locales',
            help='번역할 로케일만 지정 (예: en, zh_Hans). 여러 번 지정 가능.',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='이미 번역된 항목도 다시 번역합니다.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='실제로 .po 파일을 수정하지 않고 번역만 시도합니다.',
        )

    def handle(self, *args, **options):
        locales = options.get('locales')
        force = options.get('force', False)
        dry_run = options.get('dry_run', False)

        if dry_run:
            self.stdout.write('(dry-run: .po 파일을 수정하지 않습니다.)')

        try:
            total = 0
            for loc, deepl_code, count in run_translate_po(locales=locales, force=force, dry_run=dry_run):
                total += count
                self.stdout.write(self.style.SUCCESS(f'  {loc} ({deepl_code}): {count}건 번역'))
            self.stdout.write(self.style.SUCCESS(f'총 {total}건 번역 완료.'))
            if not dry_run and total:
                self.stdout.write('  python manage.py compilemessages 로 .mo를 컴파일하세요 (gettext 필요).')
        except CommandError as e:
            raise e
        except Exception as e:
            raise CommandError(str(e))
