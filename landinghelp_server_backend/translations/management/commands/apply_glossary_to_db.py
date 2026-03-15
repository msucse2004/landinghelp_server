"""
용어 사전(glossary)에 등록된 번역으로 DB를 덮어씁니다.
예: key="원"인 행의 en, es 등을 KRW로 수정(Circle 등 잘못된 값 보정).

  python manage.py apply_glossary_to_db
"""
from django.core.management.base import BaseCommand

from translations.glossary import TRANSLATION_GLOSSARY
from translations.models import LANG_CODE_TO_FIELD, StaticTranslation
from translations.utils import invalidate_cache


class Command(BaseCommand):
    help = "Glossary terms (e.g. 원→KRW) apply to StaticTranslation DB."

    def handle(self, *args, **options):
        invalidate_cache()
        updated = 0
        for source_ko, by_lang in TRANSLATION_GLOSSARY.items():
            if not source_ko or not by_lang:
                continue
            obj, _ = StaticTranslation.objects.get_or_create(
                key=source_ko.strip(),
                defaults={"ko": source_ko.strip(), "en": "", "es": "", "zh_hans": "", "zh_hant": "", "vi": ""},
            )
            fields_to_update = []
            for lang_code, value in by_lang.items():
                if not value:
                    continue
                field = LANG_CODE_TO_FIELD.get(lang_code)
                if not field:
                    continue
                if getattr(obj, field, None) != value:
                    setattr(obj, field, value)
                    updated += 1
                    fields_to_update.append(field)
            if fields_to_update:
                obj.save(update_fields=fields_to_update)
        invalidate_cache()
        self.stdout.write(self.style.SUCCESS(f"Glossary applied: {updated} cells updated."))
