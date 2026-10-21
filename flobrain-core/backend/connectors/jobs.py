from django.conf import settings
from django.utils import timezone

from connectors import sdk
from connectors.models import Connection, ExternalItem
from integrations import crypto
from jobs.queue import register

JOB = "connectors.sync"
DEMO_OFF = "Demo mode: only demo connections sync"


def secret_of(connection) -> str:
    return crypto.decrypt(bytes(connection.secret_ciphertext), connection.id, connection.org_id, connection.key_version)


def is_demo(connection) -> bool:
    return (connection.config or {}).get("demo") is True


def _fail(connection, code):
    Connection.objects.filter(pk=connection.pk, status=Connection.ACTIVE).update(last_error=str(code)[:200])


@register(JOB)
def sync(payload):
    import connectors.catalog  # noqa: F401  (registers connectors in the worker)

    connection = Connection.objects.filter(pk=payload.get("connection_id"), status=Connection.ACTIVE).first()
    if connection is None:
        return
    connector = sdk.get(connection.connector)
    demo_mode = bool(getattr(settings, "DEMO_MODE", False))
    if is_demo(connection):
        # Canned items, never the network. A demo connection on a real server does nothing.
        if not demo_mode:
            return _fail(connection, "Demo connection: sync is off outside demo mode")
        items = connector.demo_items(connection) if connector else []
    else:
        if demo_mode:
            return _fail(connection, DEMO_OFF)  # demo servers never call the network
        if not connection.secret_ciphertext:
            return  # disconnected: nothing runs any more
        try:
            items = connector.sync(connection, secret_of(connection)) if connector else []
        except (sdk.ConnectorError, crypto.CredentialCryptoError) as exc:
            return _fail(connection, getattr(exc, "code", "error"))
    # A disconnect during the sync wins: re-check before writing anything.
    if not Connection.objects.filter(pk=connection.pk, status=Connection.ACTIVE).exists():
        return
    seen = set()
    for item in items[:1000]:
        if not isinstance(item, dict) or not item.get("kind") or not item.get("external_id"):
            continue
        url = str(item.get("url") or "")
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        defaults = {
            "org_id": connection.org_id,
            "title": str(item.get("title") or "")[:300],
            "url": url if url.startswith("https://") else "",  # never javascript: or http links, whatever the connector
            "state": str(item.get("state") or "")[:24],
            "meta": meta,
            "external_updated_at": item.get("external_updated_at"),
            "updated_at": timezone.now(),
        }
        row, _ = ExternalItem.objects.update_or_create(
            connection=connection, kind=item["kind"], external_id=str(item["external_id"])[:128], defaults=defaults
        )
        seen.add(row.pk)
    if connector is not None and connector.prunes and len(items) <= 1000:
        ExternalItem.objects.filter(connection=connection).exclude(pk__in=seen).delete()
    Connection.objects.filter(pk=connection.pk).update(last_sync_at=timezone.now(), last_error="")
