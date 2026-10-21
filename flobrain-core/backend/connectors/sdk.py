"""Connector SDK (Phase 15).

A connector declares what it is and implements a few methods. Core code never changes
to add one: register it in ``connectors.catalog`` and it appears in the catalog, gets
the connect/sync/disconnect endpoints, and runs on the worker.

- ``auth``: ``"token"`` (the admin pastes a token) or ``"oauth2"`` (needs the platform's
  client id and secret in env; until then the connector shows as "not configured").
- ``validate(secret, config)`` -> cleaned config, or raise ``ConnectorError``.
- ``sync(connection, secret)`` -> list of item dicts ``{kind, external_id, title, url, state}``.
  Read connectors only read. Anything that writes outside FloBrain goes through approved
  actions (Decision 33), never through ``sync``.

- ``prunes``: True when ``sync`` returns the full list, so items it no longer returns are removed
  (Notion pages that were deleted). False keeps old items (GitHub returns only recent ones).
- Demo mode (``settings.DEMO_MODE``): ``validate_offline(config)`` checks the config without any
  network call, and ``demo_items(connection)`` returns canned items for connections marked
  ``config["demo"]``. Demo mode never calls the network.

All network calls use ``platform_api.net.fetch``: https, public IPs only, no redirects.
"""

from dataclasses import dataclass, field


class ConnectorError(Exception):
    def __init__(self, code: str, details: str = ""):
        super().__init__(code)
        self.code = code
        self.details = details or code


@dataclass
class Connector:
    key: str
    name: str
    description: str
    auth: str = "token"
    kind: str = "read"  # read | write | publish
    config_fields: list = field(default_factory=list)  # [{name, label, hint}]
    env: tuple = ()  # settings that must be set for this connector to be available
    prunes: bool = False
    token_hint: str = ""

    def configured(self) -> bool:
        from django.conf import settings

        return all(getattr(settings, name, "") for name in self.env)

    def validate(self, secret: str, config: dict) -> dict:
        raise ConnectorError("not_configured", f"{self.name} is not available yet")

    def sync(self, connection, secret: str) -> list:
        return []

    def validate_offline(self, config: dict) -> dict:
        raise ConnectorError("not_configured", f"{self.name} has no demo mode")

    def demo_items(self, connection) -> list:
        return []

    def describe(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "auth": self.auth,
            "kind": self.kind,
            "config_fields": self.config_fields,
            "token_hint": self.token_hint,
            "available": self.configured() and type(self).validate is not Connector.validate,
        }


_REGISTRY: dict = {}


def register(connector: Connector) -> Connector:
    _REGISTRY[connector.key] = connector
    return connector


def get(key: str):
    return _REGISTRY.get(key)


def catalog():
    return list(_REGISTRY.values())
