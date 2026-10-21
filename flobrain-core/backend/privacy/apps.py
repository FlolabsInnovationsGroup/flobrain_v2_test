from django.apps import AppConfig


class PrivacyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "privacy"
    verbose_name = "Privacy center"

    def ready(self):
        from privacy import jobs  # noqa: F401
