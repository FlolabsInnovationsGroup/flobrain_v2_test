from django.apps import AppConfig


class ImportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "imports"
    verbose_name = "Bring rooms, pages and files from Slack, Notion and Google Drive"

    def ready(self):
        from imports import jobs  # noqa: F401  (registers the worker jobs)
