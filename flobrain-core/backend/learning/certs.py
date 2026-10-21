"""Certificate signing (Decision 40): Ed25519 over a canonical JSON of the certificate data.

``CERTIFICATE_SIGNING_KEY`` is the raw 32-byte private key, base64. Empty: issuing returns 501,
except in demo mode (``DEMO_MODE``), where a demo key is generated and kept in the demo org's
settings (``demo_certificate_key``) so every process and restart signs with the same key. Its
key id starts with ``demo-`` and the public page says "Signed with a demo key". Without a demo org
yet, the demo key lives in this process only.
``CERTIFICATE_PREVIOUS_PUBLIC_KEYS`` (comma-separated base64 public keys) keeps certificates signed
with a retired key verifiable after rotation.
The public key is published at ``/api/public/certificates/public-key`` so anyone can verify.
"""

import base64
import hashlib
import json
import os

from django.conf import settings

DEMO_SETTING = "demo_certificate_key"
DEMO_PREFIX = "demo-"
_PROCESS_DEMO_SEED = []  # fallback when there is no demo org yet


class NotConfigured(Exception):
    pass


def _decode32(raw):
    try:
        key = base64.b64decode(str(raw or ""), validate=True)
    except ValueError:
        return None
    return key if len(key) == 32 else None


def using_demo_key() -> bool:
    return not (getattr(settings, "CERTIFICATE_SIGNING_KEY", "") or "") and bool(getattr(settings, "DEMO_MODE", False))


def store_demo_key(org) -> bytes:
    """Demo mode: the demo org's signing key, created on first use (row-locked, so processes agree)."""
    from django.db import transaction

    from organizations.models import Organization

    with transaction.atomic():
        row = Organization.objects.select_for_update().get(pk=org.pk)
        current = _decode32((row.settings or {}).get(DEMO_SETTING))
        if current:
            return current
        seed = _PROCESS_DEMO_SEED[0] if _PROCESS_DEMO_SEED else os.urandom(32)
        row.settings = {**(row.settings or {}), DEMO_SETTING: base64.b64encode(seed).decode()}
        row.save(update_fields=["settings"])
        return seed


def _demo_seed() -> bytes:
    from django.db import DatabaseError

    from organizations.models import Organization

    try:
        from demo.seed import DEMO_SLUG

        org = Organization.objects.filter(slug=DEMO_SLUG).only("id", "settings").first()
        if org is not None and (org.settings or {}).get("demo") is True:
            return _decode32((org.settings or {}).get(DEMO_SETTING)) or store_demo_key(org)
    except DatabaseError:
        pass
    if not _PROCESS_DEMO_SEED:
        _PROCESS_DEMO_SEED.append(os.urandom(32))
    return _PROCESS_DEMO_SEED[0]


def _private():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    raw = getattr(settings, "CERTIFICATE_SIGNING_KEY", "") or ""
    if not raw:
        if getattr(settings, "DEMO_MODE", False):
            return Ed25519PrivateKey.from_private_bytes(_demo_seed())
        raise NotConfigured()
    try:
        key = base64.b64decode(raw)
    except ValueError as exc:
        raise NotConfigured() from exc
    if len(key) != 32:
        raise NotConfigured()
    return Ed25519PrivateKey.from_private_bytes(key)


def public_key_b64() -> str:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    return base64.b64encode(_private().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()


def key_id() -> str:
    kid = hashlib.sha256(public_key_b64().encode()).hexdigest()[:16]
    return DEMO_PREFIX + kid[:11] if using_demo_key() else kid


def is_demo_key_id(kid: str) -> bool:
    return str(kid or "").startswith(DEMO_PREFIX)


def canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(data: dict) -> str:
    return base64.b64encode(_private().sign(canonical(data))).decode()


def _id_for(public_b64: str) -> str:
    return hashlib.sha256(public_b64.encode()).hexdigest()[:16]


def key_ring() -> dict:
    """key_id → public key (base64): the current key and any retired ones."""
    ring = {}
    for raw in str(getattr(settings, "CERTIFICATE_PREVIOUS_PUBLIC_KEYS", "") or "").split(","):
        raw = raw.strip()
        if raw:
            ring[_id_for(raw)] = raw
    try:
        current = public_key_b64()
        ring[key_id()] = current
    except NotConfigured:
        pass
    return ring


def verify(data: dict, signature: str, signed_key_id: str = "") -> bool:
    """Checks against the key the certificate names (current or retired). Unknown key: False."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    ring = key_ring()
    public = ring.get(signed_key_id) if signed_key_id else (public_key_b64() if ring else None)
    if not public:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public)).verify(base64.b64decode(signature), canonical(data))
        return True
    except (InvalidSignature, ValueError):
        return False


def build_data(org, user, kind, path=None, include_details=False) -> dict:
    """Facts only, from the records: hours by tag, finished tasks, projects, dates.
    Project and tag names are internal, so they appear only when the issuer asks (review 10-13)."""
    from django.utils import timezone

    from organizations.models import OrgMembership
    from tasks.models import Task
    from timetracking.models import TimeEntry

    total, by_tag = 0.0, {}
    for entry in TimeEntry.objects.filter(org=org, user=user, ended_at__isnull=False).prefetch_related("tags"):
        seconds = max(0.0, (entry.ended_at - entry.started_at).total_seconds())
        total += seconds
        for name in [t.name for t in entry.tags.all()] or ["untagged"]:
            by_tag[name] = by_tag.get(name, 0.0) + seconds
    by_tag = {name: round(seconds / 3600, 1) for name, seconds in sorted(by_tag.items())}
    done = Task.objects.filter(org=org, assignments__user=user, status=Task.STATUS_DONE)
    projects = sorted({name for name in done.exclude(project__isnull=True).values_list("project__name", flat=True)})
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    data = {
        "kind": kind,
        "recipient": user.username or user.email.split("@")[0],
        "organization": org.name,
        "from": (membership.created_at.date().isoformat() if membership else None),
        "to": timezone.localdate().isoformat(),
        "hours_total": round(total / 3600, 1),
        "hours_by_category": by_tag if include_details else {},
        "tasks_completed": done.count(),
        "projects": projects[:20] if include_details else [],
        "projects_count": len(projects),
    }
    if path is not None:
        data["learning_path"] = path.name
    return data
