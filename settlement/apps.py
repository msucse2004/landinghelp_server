from django.apps import AppConfig


class SettlementConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'settlement'
    verbose_name = '정착 서비스'

    def ready(self):
        import settlement.signals  # noqa: F401
