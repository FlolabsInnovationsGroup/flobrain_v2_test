from django.apps import AppConfig


class BridgesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bridges"
    verbose_name = "Slack and Microsoft Teams bridges: buddies and approvals inside the chat people already use"

    def ready(self):
        from django.db.models.signals import post_save

        from actions.models import ActionProposal
        from bridges import engine

        post_save.connect(engine.on_proposal_saved, sender=ActionProposal, dispatch_uid="bridges.mirror_proposal")
