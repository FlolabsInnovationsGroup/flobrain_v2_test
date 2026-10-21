from django.apps import AppConfig


class AgentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "agents"
    verbose_name = "Scheduled agents"

    def ready(self):
        from agents import jobs, signals  # noqa: F401
