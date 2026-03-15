"""
gettext 없이 Babel로 .po → .mo 컴파일 (Windows 등에서 사용).
  python manage.py compilemessages_py
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def compile_po_to_mo(po_path: Path, mo_path: Path, locale_id: str) -> bool:
    try:
        from babel.messages.pofile import read_po
        from babel.messages.mofile import write_mo
        from babel import Locale
    except ImportError as e:
        raise CommandError(
            'Babel이 필요합니다. pip install Babel 후 다시 실행하세요. (%s)' % e
        )
    try:
        loc = Locale.parse(locale_id.replace('-', '_'))
    except Exception:
        loc = Locale.parse('en')
    with open(po_path, 'r', encoding='utf-8') as f:
        catalog = read_po(f, locale=loc)
    mo_path.parent.mkdir(parents=True, exist_ok=True)
    with open(mo_path, 'wb') as f:
        write_mo(f, catalog)
    return True


class Command(BaseCommand):
    help = 'gettext 없이 Babel로 locale/*/LC_MESSAGES/django.po → django.mo 컴파일'

    def handle(self, *args, **options):
        locale_paths = getattr(settings, 'LOCALE_PATHS', None)
        if not locale_paths:
            raise CommandError('settings.LOCALE_PATHS가 비어 있습니다.')
        base = Path(locale_paths[0]).resolve()
        if not base.exists():
            raise CommandError('locale 경로가 없습니다: %s' % base)
        compiled = 0
        for locale_dir in base.iterdir():
            if not locale_dir.is_dir():
                continue
            po_file = locale_dir / 'LC_MESSAGES' / 'django.po'
            mo_file = locale_dir / 'LC_MESSAGES' / 'django.mo'
            if not po_file.exists():
                continue
            locale_id = locale_dir.name
            compile_po_to_mo(po_file, mo_file, locale_id)
            compiled += 1
            self.stdout.write(self.style.SUCCESS('  %s → django.mo' % locale_id))
        self.stdout.write(self.style.SUCCESS('총 %d개 로케일 컴파일 완료.' % compiled))
