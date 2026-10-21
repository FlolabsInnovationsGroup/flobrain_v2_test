from django.apps import AppConfig


class BuddyMemoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "buddy_memory"
    verbose_name = "What buddies remember about a person or team, visible and deletable"

    def ready(self):
        from buddy_memory import signals

        signals.connect()
        _demo_tick()


def _demo_tick():
    """Add ``tick_buddy_memory`` to the demo ticker's commands (demo/ticker.py is not ours to edit)."""
    try:
        from demo import ticker
    except Exception:  # noqa: BLE001 - no demo app, nothing to add
        return
    if "tick_buddy_memory" not in ticker.COMMANDS:
        ticker.COMMANDS = tuple(ticker.COMMANDS) + ("tick_buddy_memory",)
