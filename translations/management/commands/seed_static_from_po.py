"""
locale/*/LC_MESSAGES/django.po 내용을 StaticTranslation(고정 번역 CSV) 테이블에 채웁니다.
실행 후 Admin에서 "전체 언어 CSV 내보내기"하면 .po에 있던 문구가 CSV로 나갑니다.

  python manage.py seed_static_from_po
  python manage.py seed_static_from_po --locale en --locale ko
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


# locale 디렉터리 이름 -> settings.LANGUAGES 언어 코드
LOCALE_TO_LANG = {
    'en': 'en',
    'ko': 'ko',
    'es': 'es',
    'vi': 'vi',
    'zh_hans': 'zh-hans',
    'zh_hant': 'zh-hant',
}


def locale_dir_to_lang(locale_dir_name: str) -> str | None:
    n = locale_dir_name.replace('-', '_').lower()
    return LOCALE_TO_LANG.get(n)


def _unescape_po(s: str) -> str:
    if not s:
        return ''
    return s.replace('\\n', '\n').replace('\\"', '"').replace('\\t', '\t')


def _read_po_entries(po_path: Path):
    """Parse .po file and yield (msgid, msgstr). Uses polib if available."""
    try:
        import polib
        po = polib.pofile(str(po_path))
        for entry in po:
            if not entry.msgid or entry.obsolete:
                continue
            msgstr = (entry.msgstr or '').strip() or entry.msgid
            yield (entry.msgid, msgstr)
        return
    except ImportError:
        pass
    # Fallback: simple line-by-line parse (single-line msgid/msgstr only)
    import re
    text = po_path.read_text(encoding='utf-8')
    for m in re.finditer(r'msgid\s+"((?:[^"\\]|\\.)*)"\s*\n\s*msgstr\s+"((?:[^"\\]|\\.)*)"', text):
        msgid = _unescape_po(m.group(1))
        msgstr = _unescape_po(m.group(2)) or msgid
        if msgid:
            yield (msgid, msgstr)


def run_seed(locales=None):
    locale_paths = getattr(settings, 'LOCALE_PATHS', None)
    if not locale_paths:
        raise CommandError('settings.LOCALE_PATHS가 비어 있습니다.')
    base = Path(locale_paths[0]).resolve()
    if not base.exists():
        raise CommandError(f'locale 경로가 없습니다: {base}')

    from translations.models import StaticTranslation

    if locales:
        dirs = [base / loc for loc in locales if (base / loc).is_dir()]
    else:
        dirs = [d for d in base.iterdir() if d.is_dir()]

    total = 0
    for locale_dir in dirs:
        lang = locale_dir_to_lang(locale_dir.name)
        if not lang:
            continue
        po_path = locale_dir / 'LC_MESSAGES' / 'django.po'
        if not po_path.exists():
            continue
        count = 0
        for msgid, msgstr in _read_po_entries(po_path):
            if not msgid:
                continue
            StaticTranslation.objects.update_or_create(
                key=msgid,
                language_code=lang,
                defaults={'value': msgstr or msgid},
            )
            count += 1
        total += count
        yield locale_dir.name, lang, count
    yield (None, None, total)


class Command(BaseCommand):
    help = 'locale/*/django.po 내용을 고정 번역(StaticTranslation) 테이블에 채우기'

    def add_arguments(self, parser):
        parser.add_argument(
            '--locale',
            action='append',
            dest='locales',
            help='시드할 로케일만 지정 (예: en, ko). 여러 번 지정 가능.',
        )

    def handle(self, *args, **options):
        locales = options.get('locales')
        try:
            for loc, lang, count in run_seed(locales=locales):
                if loc is None:
                    self.stdout.write(self.style.SUCCESS(f'총 {count}건 시드 완료.'))
                    break
                self.stdout.write(self.style.SUCCESS(f'  {loc} ({lang}): {count}건'))
        except CommandError as e:
            raise e
        except Exception as e:
            raise CommandError(str(e))

        try:
            from translations.utils import invalidate_cache
            invalidate_cache()
            self.stdout.write('고정 번역 캐시를 초기화했습니다. 이제 CSV 내보내기 시 데이터가 포함됩니다.')
        except Exception:
            pass
