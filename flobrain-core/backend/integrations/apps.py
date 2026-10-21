from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations"
    verbose_name = "Integrations"

    def ready(self):
        # Write-back connector actions become approval-gated tools (growth round W4).
        from integrations.write.tools import register_all

        register_all()
