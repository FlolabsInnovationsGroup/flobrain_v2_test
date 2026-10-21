from django.apps import AppConfig


class PlatformApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "platform_api"
    verbose_name = "Public API, webhooks and MCP"

    def ready(self):
        from platform_api import jobs, signals  # noqa: F401
        from platform_api import mcp_tools_extra

        mcp_tools_extra.register()  # MCP hub: the approval-gated "automations.run" action
