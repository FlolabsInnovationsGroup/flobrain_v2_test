"""Provider and action declarations for write-back connectors.

A provider says how to connect (OAuth 2 authorization code with PKCE, or an API key for Odoo),
which HTTPS hosts FloBrain may call for it, and which actions it offers. An action has a JSON
schema for its arguments (the ``actions.schema`` subset), a preview line for the approval card,
a risk level, the OAuth scopes it needs, an executor and a demo result.

OAuth client ids and secrets come only from the environment:
``FLOBRAIN_OAUTH_<PROVIDER>_CLIENT_ID`` and ``FLOBRAIN_OAUTH_<PROVIDER>_CLIENT_SECRET``. Until both
exist the provider shows as "not set up".
"""

import os
import re
from dataclasses import dataclass, field
from typing import Callable

from django.conf import settings

HIGH, MEDIUM = "high", "medium"


def env(name: str) -> str:
    """A setting or environment value (settings first so tests can override it). Never logged."""
    value = getattr(settings, name, None)
    if value in (None, ""):
        value = os.environ.get(name, "")
    return str(value or "").strip()


def normalize_scope(scope: str) -> str:
    """Compare scopes by their last path part: ``https://graph.microsoft.com/Mail.Send`` == ``Mail.Send``."""
    return scope.strip().rstrip("/").rsplit("/", 1)[-1].lower()


@dataclass
class Action:
    key: str
    label: str
    description: str
    schema: dict
    risk: str
    scopes: tuple
    preview: Callable  # (args, connection|None) -> str
    run: Callable  # (client, args, connection) -> {"id", "url", "title"}
    demo: Callable  # (args) -> {"id", "url", "title"}
    validate: Callable | None = None  # (args) -> None; raise ValueError with a plain message
    provider: str = ""

    @property
    def tool_key(self) -> str:
        return f"{self.provider}.{self.key}"


@dataclass
class Provider:
    key: str
    name: str
    description: str
    auth: str = "oauth2"  # oauth2 | api_key
    per_user: bool = False
    authorize_url: Callable | str = ""
    token_url: Callable | str = ""
    base_scopes: tuple = ()
    auth_params: dict = field(default_factory=dict)
    scope_separator: str = " "
    hosts: frozenset = frozenset()
    host_rule: Callable | None = None  # (host, connection) -> bool, for hosts that depend on the connection
    auth_scheme: str = "Bearer"
    identify: Callable | None = None  # (client, token_result) -> (label, config)
    actions: list = field(default_factory=list)
    demo_label: str = ""
    demo_config: dict = field(default_factory=dict)

    # --- configuration -----------------------------------------------------------------
    @property
    def env_prefix(self) -> str:
        return f"FLOBRAIN_OAUTH_{self.key.upper()}"

    def env_names(self) -> list[str]:
        if self.auth != "oauth2":
            return []
        return [f"{self.env_prefix}_CLIENT_ID", f"{self.env_prefix}_CLIENT_SECRET"]

    def client_id(self) -> str:
        return env(f"{self.env_prefix}_CLIENT_ID")

    def client_secret(self) -> str:
        return env(f"{self.env_prefix}_CLIENT_SECRET")

    def configured(self) -> bool:
        if self.auth != "oauth2":
            return True
        return bool(self.client_id() and self.client_secret())

    def resolve(self, value) -> str:
        return value() if callable(value) else value

    def scopes(self) -> list[str]:
        out = list(self.base_scopes)
        for action in self.actions:
            out.extend(action.scopes)
        return list(dict.fromkeys(out))

    def host_allowed(self, host: str, connection=None) -> bool:
        host = (host or "").lower().rstrip(".")
        if host in self.hosts:
            return True
        return bool(self.host_rule and self.host_rule(host, connection))

    def auth_header(self, token: str) -> dict:
        return {"Authorization": f"{self.auth_scheme} {token}"}

    def action(self, key: str):
        return next((a for a in self.actions if a.key == key), None)


_PROVIDERS: dict[str, Provider] = {}


def register(provider: Provider) -> Provider:
    for action in provider.actions:
        action.provider = provider.key
    _PROVIDERS[provider.key] = provider
    return provider


def providers() -> list[Provider]:
    _load()
    return list(_PROVIDERS.values())


def get(key: str) -> Provider | None:
    _load()
    return _PROVIDERS.get(key)


def actions() -> list[Action]:
    return [action for provider in providers() for action in provider.actions]


def action_for(tool_key: str) -> tuple[Provider | None, Action | None]:
    provider_key, _, action_key = (tool_key or "").partition(".")
    provider = get(provider_key)
    return provider, (provider.action(action_key) if provider else None)


def tool_keys() -> list[str]:
    return [action.tool_key for action in actions()]


def _load():
    if not _PROVIDERS:
        import integrations.write.catalog  # noqa: F401  (registers every provider)


# --- shared schema pieces and checks ------------------------------------------------------

EMAIL = {"type": "string", "format": "email", "maxLength": 254}
EMAILS = {"type": "array", "items": EMAIL, "maxItems": 20}
DECIMAL_RE = re.compile(r"^\d{1,12}(\.\d{1,2})?$")
NO_CONTROL_RE = re.compile(r"[\r\n\x00-\x1f\x7f]")


def text(max_length: int, min_length: int = 0) -> dict:
    out = {"type": "string", "maxLength": max_length}
    if min_length:
        out["minLength"] = min_length
    return out


def obj(properties: dict, required: list) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def single_line(value: str, name: str) -> None:
    if value and NO_CONTROL_RE.search(value):
        raise ValueError(f"{name} must be one line")


def decimal(value: str | None, name: str) -> None:
    if value not in (None, "") and not DECIMAL_RE.match(str(value)):
        raise ValueError(f"{name} must be a number like 1500 or 1500.50")


def recipients(values: list) -> str:
    shown = ", ".join(values[:3])
    more = len(values) - 3
    return f"{shown} and {more} more" if more > 0 else shown


def short(value: str, limit: int = 80) -> str:
    value = " ".join((value or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"
