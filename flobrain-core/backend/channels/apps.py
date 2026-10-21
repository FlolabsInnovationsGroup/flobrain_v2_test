from django.apps import AppConfig


class ChannelsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "channels"
    verbose_name = "Channels: WhatsApp, Telegram and the customer buddy"

    def ready(self):
        from corsheaders.signals import check_request_enabled

        from channels import inbound  # noqa: F401  (registers the inbound job)
        from channels.cors import allow_site_origins

        check_request_enabled.connect(allow_site_origins, dispatch_uid="channels.website_cors")
