from django.apps import AppConfig


class MessagingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'messaging'
    verbose_name = '메시지'

    def ready(self):
        import messaging.signals  # noqa: F401
