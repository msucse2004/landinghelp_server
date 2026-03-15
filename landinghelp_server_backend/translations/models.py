from django.db import models


# CSV/Admin 컬럼 순서. DB 필드명(언어코드에 - 있으면 _ 로 저장)
LANG_COLUMNS = ['ko', 'en', 'es', 'zh_hans', 'zh_hant', 'vi']
# CSV 헤더용 (zh-hans, zh-hant)
LANG_CSV_HEADERS = ['key', 'ko', 'en', 'es', 'zh-hans', 'zh-hant', 'vi']
# language_code -> DB 필드명
LANG_CODE_TO_FIELD = {
    'ko': 'ko',
    'en': 'en',
    'es': 'es',
    'zh-hans': 'zh_hans',
    'zh-hant': 'zh_hant',
    'vi': 'vi',
}
FIELD_TO_LANG_CODE = {'ko': 'ko', 'en': 'en', 'es': 'es', 'zh_hans': 'zh-hans', 'zh_hant': 'zh-hant', 'vi': 'vi'}


class StaticTranslation(models.Model):
    """
    고정 문구별 번역. key 1개당 한 행, 언어별 컬럼(ko, en, es, zh_hans, zh_hant, vi).
    CSV import/export: key, ko, en, es, zh-hans, zh-hant, vi
    """
    key = models.CharField(
        '원문(키)',
        max_length=500,
        unique=True,
        db_index=True,
        help_text='템플릿/코드에서 사용하는 문구(예: 로그아웃, 이메일)',
    )
    ko = models.CharField('한국어', max_length=1000, blank=True, default='')
    en = models.CharField('English', max_length=1000, blank=True, default='')
    es = models.CharField('Español', max_length=1000, blank=True, default='')
    zh_hans = models.CharField('中文(简体)', max_length=1000, blank=True, default='')
    zh_hant = models.CharField('中文(繁體)', max_length=1000, blank=True, default='')
    vi = models.CharField('Tiếng Việt', max_length=1000, blank=True, default='')

    class Meta:
        verbose_name = '고정 번역'
        verbose_name_plural = '고정 번역'
        ordering = ['key']

    def __str__(self):
        return f'{self.key}'

    def get_value_for_lang(self, language_code):
        """language_code(예: ko, zh-hans)에 해당하는 값 반환."""
        field = LANG_CODE_TO_FIELD.get(language_code) or language_code.replace('-', '_')
        return getattr(self, field, None) or ''
