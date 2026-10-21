from django.apps import AppConfig


class BridgesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bridges"
    verbose_name = "Slack and Microsoft Teams bridges: buddies and approvals inside the chat people already use"
