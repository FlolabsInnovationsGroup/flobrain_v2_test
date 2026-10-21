"""Platform setup read from the environment (settings first so tests can override). Never logged."""

import os

from django.conf import settings

SLACK_ENV = ("FLOBRAIN_SLACK_CLIENT_ID", "FLOBRAIN_SLACK_CLIENT_SECRET", "FLOBRAIN_SLACK_SIGNING_SECRET")
TEAMS_ENV = ("FLOBRAIN_TEAMS_APP_ID", "FLOBRAIN_TEAMS_APP_SECRET")


def env(name: str) -> str:
    value = getattr(settings, name, None)
    if value in (None, ""):
        value = os.environ.get(name, "")
    return str(value or "").strip()


def missing(names) -> list[str]:
    return [n for n in names if not env(n)]


def slack_ready() -> bool:
    return not missing(SLACK_ENV)


def teams_ready() -> bool:
    return not missing(TEAMS_ENV)


def api_base() -> str:
    return (getattr(settings, "PUBLIC_API_BASE_URL", "") or "http://localhost:8000").rstrip("/")


def frontend_base() -> str:
    return (getattr(settings, "FRONTEND_BASE_URL", "") or "").rstrip("/")


def slack_redirect_uri() -> str:
    return f"{api_base()}/api/v2/bridges/slack/oauth/callback"


def endpoints() -> dict:
    base = api_base()
    return {
        "slack_events": f"{base}/api/v2/hooks/slack/events",
        "slack_commands": f"{base}/api/v2/hooks/slack/commands",
        "slack_interactions": f"{base}/api/v2/hooks/slack/interactions",
        "slack_redirect": slack_redirect_uri(),
        "teams_messages": f"{base}/api/v2/hooks/teams/messages",
    }


def status() -> dict:
    """What the server has; names of missing variables, never values."""
    return {
        "slack": {"ready": slack_ready(), "missing": missing(SLACK_ENV)},
        "teams": {"ready": teams_ready(), "missing": missing(TEAMS_ENV), "bot_id": env("FLOBRAIN_TEAMS_APP_ID")},
        "endpoints": endpoints(),
    }
