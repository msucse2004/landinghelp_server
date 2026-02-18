from django.apps import AppConfig


class ContentConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'content'
    verbose_name = '컨텐츠'

    def ready(self):
        from django.contrib import admin
        admin.site.index_template = 'admin/custom_index.html'
