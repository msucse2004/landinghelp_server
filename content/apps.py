from django.apps import AppConfig


class ContentConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'content'
    verbose_name = '컨텐츠'

    def ready(self):
        import content.signals  # noqa: F401 - 캐러셀/콘텐츠 저장 시 모든 언어 번역 후 CSV 추가
        from django.contrib import admin
        admin.site.index_template = 'admin/custom_index.html'
