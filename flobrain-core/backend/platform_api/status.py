"""The public status projection (Phase 14f) and status email subscriptions.

``projection()`` is the only shape that leaves for the public: platform-wide incidents marked
public, component states derived from the open ones, no org data and no author. It feeds both
``manage.py export_status`` (static hosting that stays up when the API is down) and
``GET /api/public/status``.
"""

import secrets

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from jobs.queue import enqueue, register
from platform_api.models import Incident, StatusSubscription, hash_token

COMPONENTS = ("API", "Web app", "Realtime", "AI", "Content Studio", "Webhooks")
RANK = {"minor": "degraded", "major": "partial_outage", "critical": "major_outage"}
ORDER = ["operational", "degraded", "partial_outage", "major_outage"]
NOTIFY_JOB = "status.notify"
MAX_RECIPIENTS = 5000


def public_incident(i) -> dict:
    return {
        "id": str(i.id),
        "title": i.title,
        "severity": i.severity,
        "status": i.status,
        "components": i.components,
        "impact": i.impact,
        "mitigation": i.mitigation,
        "user_action": i.user_action,
        "next_update_at": i.next_update_at.isoformat() if i.next_update_at else None,
        "updates": [{"at": u.get("at"), "status": u.get("status"), "message": u.get("message")} for u in (i.updates or []) if isinstance(u, dict)],
        "created_at": i.created_at.isoformat(),
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
    }


def projection() -> dict:
    rows = list(Incident.objects.filter(org__isnull=True, is_public=True).order_by("-created_at")[:50])
    state = {c: "operational" for c in COMPONENTS}
    for incident in rows:
        if incident.status == "resolved":
            continue
        for component in incident.components or []:
            if component in state:
                worse = RANK.get(incident.severity, "degraded")
                if ORDER.index(worse) > ORDER.index(state[component]):
                    state[component] = worse
    overall = max(state.values(), key=ORDER.index) if state else "operational"
    return {
        "generated_at": timezone.now().isoformat(),
        "overall": overall,
        "components": [{"name": c, "status": s} for c, s in state.items()],
        "incidents": [public_incident(i) for i in rows],
    }


# --- subscriptions -------------------------------------------------------------------------


def _link(**query):
    from urllib.parse import urlencode

    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/status?{urlencode(query)}"


def subscribe(email: str):
    """Create or refresh a pending subscription and email a confirm link. Says nothing about
    whether the address was already subscribed (the caller always answers the same)."""
    email = email.strip().lower()
    sub = StatusSubscription.objects.filter(email=email).first()
    if sub and sub.confirmed_at:
        return sub
    if sub and (timezone.now() - sub.confirm_sent_at).total_seconds() < 600:
        return sub  # one confirm email per 10 minutes per address
    confirm = secrets.token_urlsafe(24)
    if sub is None:
        sub = StatusSubscription(email=email)
    sub.confirm_hash, sub.confirm_sent_at = hash_token(confirm), timezone.now()
    sub.save()
    send_mail(
        subject="Confirm FloBrain status updates",
        message=f"Confirm that you want emails when FloBrain has an incident:\n{_link(confirm=confirm)}\n\nIf you did not ask for this, ignore this email.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=True,
    )
    return sub


def confirm(token: str):
    sub = StatusSubscription.objects.filter(confirm_hash=hash_token(token or ""), confirmed_at__isnull=True).exclude(confirm_hash="").first()
    if sub is None:
        return None
    sub.confirmed_at, sub.confirm_hash = timezone.now(), ""
    sub.save(update_fields=["confirmed_at", "confirm_hash"])
    return sub


_SIGNER_SALT = "status-unsubscribe"


def unsubscribe_token(sub) -> str:
    from django.core import signing

    return signing.Signer(salt=_SIGNER_SALT).sign(str(sub.id))


def unsubscribe(token: str) -> bool:
    from django.core import signing

    try:
        sub_id = signing.Signer(salt=_SIGNER_SALT).unsign(str(token or ""))
    except signing.BadSignature:
        return False
    from django.core.exceptions import ValidationError

    try:
        deleted, _ = StatusSubscription.objects.filter(pk=sub_id).delete()
    except (ValueError, ValidationError):
        return False
    return bool(deleted)


def notify_subscribers(incident):
    """Queue the email for a public platform incident update."""
    if incident.org_id is None and incident.is_public:
        enqueue(NOTIFY_JOB, {"incident": str(incident.id)})


@register(NOTIFY_JOB)
def _notify_job(payload):
    incident = Incident.objects.filter(pk=payload.get("incident"), org__isnull=True, is_public=True).first()
    if incident is None:
        return {"sent": 0}
    last = (incident.updates or [{}])[-1] if incident.updates else {}
    sent = 0
    for sub in StatusSubscription.objects.filter(confirmed_at__isnull=False)[:MAX_RECIPIENTS]:
        token = unsubscribe_token(sub)
        send_mail(
            subject=f"[FloBrain status] {incident.title} ({incident.status})",
            message=f"{last.get('message') or incident.impact}\n\nStatus page: {_link()}\nStop these emails: {_link(unsubscribe=token)}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[sub.email],
            fail_silently=True,
        )
        sent += 1
    return {"sent": sent}
