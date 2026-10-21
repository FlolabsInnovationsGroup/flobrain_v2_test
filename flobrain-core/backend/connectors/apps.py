from django.apps import AppConfig


class ConnectorsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "connectors"
    verbose_name = "Integrations (connector SDK)"

    def ready(self):
        from connectors import jobs  # noqa: F401
