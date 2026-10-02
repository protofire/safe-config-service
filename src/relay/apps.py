from django.apps import AppConfig


class AppsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "relay"

    def ready(self) -> None:
        import relay.signals  # noqa: F401
