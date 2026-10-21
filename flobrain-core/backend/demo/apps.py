from django.apps import AppConfig


class DemoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "demo"
    verbose_name = "Demo mode"

    def ready(self):
        from demo import checks  # noqa: F401
        from demo import ticker

        ticker.start()
