"""
요일 키(요일_일 ~ 요일_토)를 짧은 표기로 DB에 고정 저장합니다.
키: 요일_월, 한국어: 월, 영어: Mon 등 언어별 약어만 사용(파이프라인 없이 직접 반영).

  python manage.py update_weekday_translations
"""
from django.core.management.base import BaseCommand

from translations.models import StaticTranslation
from translations.utils import WEEKDAY_KEYS, invalidate_cache


# 인덱스 0=일요일, 1=월요일, ... 6=토요일. [ko, en, es, zh_hans, zh_hant, vi] 순서
WEEKDAY_VALUES_BY_LANG = {
    'ko': ['일', '월', '화', '수', '목', '금', '토'],
    'en': ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
    'es': ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'],
    'zh_hans': ['日', '一', '二', '三', '四', '五', '六'],
    'zh_hant': ['日', '一', '二', '三', '四', '五', '六'],
    'vi': ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'],
}


class Command(BaseCommand):
    help = '요일 키(요일_일~요일_토)를 한국어 월/영어 Mon 등 짧은 표기로 DB 직접 업데이트.'

    def handle(self, *args, **options):
        invalidate_cache()
        updated = 0
        for i, key in enumerate(WEEKDAY_KEYS):
            if i >= 7:
                continue
            obj, created = StaticTranslation.objects.get_or_create(
                key=key,
                defaults={'ko': '', 'en': '', 'es': '', 'zh_hans': '', 'zh_hant': '', 'vi': ''},
            )
            for field, values in WEEKDAY_VALUES_BY_LANG.items():
                if i < len(values):
                    val = values[i]
                    if getattr(obj, field, None) != val:
                        setattr(obj, field, val)
                        updated += 1
            obj.save(update_fields=['ko', 'en', 'es', 'zh_hans', 'zh_hant', 'vi'])
        invalidate_cache()
        self.stdout.write(self.style.SUCCESS(f'Weekday DB updated: 7 keys, {updated} cells written.'))
