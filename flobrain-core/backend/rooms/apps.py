from django.apps import AppConfig


class RoomsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "rooms"
    verbose_name = "Rooms"

    def ready(self):
        from rooms import signals  # noqa: F401
        from rooms import voice  # noqa: F401  (W7: voice note job + audio cleanup)
