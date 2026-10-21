from django.apps import AppConfig


class ContentStudioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "content_studio"
    verbose_name = "Content Studio"

    def ready(self):
        from content_studio import jobs  # noqa: F401
