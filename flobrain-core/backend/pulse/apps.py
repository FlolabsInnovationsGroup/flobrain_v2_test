from django.apps import AppConfig


class PulseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pulse"
    verbose_name = "FloBrain Pulse"

    def ready(self):
        from pulse import jobs  # noqa: F401
