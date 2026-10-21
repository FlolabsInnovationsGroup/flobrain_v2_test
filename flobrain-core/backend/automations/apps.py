from django.apps import AppConfig


class AutomationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "automations"
    verbose_name = "Automations: workflows, triggers, steps, approvals, proactive briefs"

    def ready(self):
        from automations import jobs, tools, triggers  # noqa: F401

        tools.register()
        triggers.connect()
        _demo_tick()


def _demo_tick():
    """Add ``tick_automations`` to the demo ticker's commands (demo/ticker.py is not ours to edit)."""
    try:
        from demo import ticker
    except Exception:  # noqa: BLE001 - no demo app, nothing to add
        return
    if "tick_automations" not in ticker.COMMANDS:
        ticker.COMMANDS = tuple(ticker.COMMANDS) + ("tick_automations",)
