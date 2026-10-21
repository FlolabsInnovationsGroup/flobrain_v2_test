from django.apps import AppConfig


class PlatformApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "platform_api"
    verbose_name = "Public API, webhooks and MCP"

    def ready(self):
        from platform_api import jobs, signals  # noqa: F401
