from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"
    verbose_name = "Notifications"

    def ready(self):
        # Job handlers must be registered in the worker too, which never loads the URLs.
        from notifications import jobs  # noqa: F401
