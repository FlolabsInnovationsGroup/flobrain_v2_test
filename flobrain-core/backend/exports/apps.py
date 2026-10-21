from django.apps import AppConfig


class ExportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "exports"
    verbose_name = "Org memory export"

    def ready(self):
        # Job handlers must be registered in the worker too, which never loads the URLs.
        from exports import jobs  # noqa: F401
