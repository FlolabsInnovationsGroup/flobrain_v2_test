"""Demo only: run the scheduled ticks inside the web process, so reminders, scheduled agents,
webhook retries, content renders and Pulse checks happen in the demo without cron.

Started by ``DemoConfig.ready`` when ``DEMO_MODE`` is on, ``DEMO_TICKS`` isn't off and we are
not under tests. Every ``DEMO_TICK_SECONDS`` (60) it runs each tick command once. On
PostgreSQL an advisory lock makes sure only one process of the deployment ticks at a time.
"""

import io
import logging
import os
import sys
import threading
import time

from django.conf import settings

logger = logging.getLogger(__name__)

COMMANDS = ("tick_tasks", "tick_agents", "tick_webhooks", "tick_content", "tick_pulse", "tick_automations", "run_data_reports", "tick_bridges")
LOCK_KEY = 7_204_311  # any constant; only demo processes take it
_started = False


def should_start() -> bool:
    if not getattr(settings, "DEMO_MODE", False) or getattr(settings, "TESTING", False):
        return False
    if str(os.environ.get("DEMO_TICKS", "1")).lower() in ("0", "false", "no", "off"):
        return False
    # Under `runserver` only the reloaded child serves requests.
    if "runserver" in sys.argv and "--noreload" not in sys.argv and os.environ.get("RUN_MAIN") != "true":
        return False
    return not any(cmd in sys.argv for cmd in ("migrate", "makemigrations", "test", "shell", "collectstatic", "run_jobs", "seed_demo", "check"))


def _tick_once():
    from django.core.management import call_command
    from django.db import close_old_connections, connection

    close_old_connections()
    locked = True
    if connection.vendor == "postgresql":
        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_KEY])
            locked = bool(cur.fetchone()[0])
    if not locked:
        return
    try:
        for name in COMMANDS:
            try:
                call_command(name, verbosity=0, stdout=io.StringIO())  # keep the API window for real errors
            except Exception:  # noqa: BLE001 - one failing tick must not stop the others
                logger.exception("demo tick %s failed", name)
    finally:
        if connection.vendor == "postgresql":
            with connection.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", [LOCK_KEY])
        close_old_connections()


def _loop(every):
    time.sleep(min(every, 15))  # let the server finish starting
    while True:
        try:
            _tick_once()
        except Exception:  # noqa: BLE001
            logger.exception("demo ticker failed")
        time.sleep(every)


def start():
    global _started
    if _started or not should_start():
        return False
    _started = True
    every = max(int(getattr(settings, "DEMO_TICK_SECONDS", 60) or 60), 15)
    threading.Thread(target=_loop, args=(every,), name="demo-ticker", daemon=True).start()
    logger.info("demo ticker started (every %ss)", every)
    return True
