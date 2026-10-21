from django.apps import AppConfig


class AutomationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "automations"
    verbose_name = "Automations: workflows, triggers, steps, approvals, proactive briefs"
