from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from pulse import metrics
from pulse.models import AlertRule

LABELS = {"error_rate": "Error rate", "p95_latency_ms": "p95 latency (ms)", "daily_cost": "AI cost"}


def evaluate(now=None) -> int:
    """Fire each active rule at most once per window. Returns how many fired."""
    from notifications.models import Notification
    from organizations.models import OrgMembership

    now = now or timezone.now()
    fired = 0
    for rule in AlertRule.objects.filter(is_active=True).select_related("org"):
        if rule.last_fired_at and rule.last_fired_at > now - timedelta(minutes=rule.window_minutes):
            continue
        value = metrics.metric_value(rule.org, rule.metric, rule.window_minutes)
        if value is None or value <= rule.threshold:
            continue
        if not AlertRule.objects.filter(pk=rule.pk, last_fired_at=rule.last_fired_at).update(last_fired_at=now):
            continue  # another ticker fired it
        fired += 1
        admins = OrgMembership.objects.filter(
            org=rule.org, employment_status="active", org_role__in=[OrgMembership.ORG_ROLE_OWNER, OrgMembership.ORG_ROLE_ADMIN]
        ).select_related("user")
        text = f"{LABELS[rule.metric]} is {round(value, 4)} over the last {rule.window_minutes} minutes (alert above {rule.threshold})."
        for m in admins:
            Notification.objects.create(org=rule.org, user=m.user, kind="pulse_alert", payload={"text": text, "metric": rule.metric})
        emails = [m.user.email for m in admins if m.user.email]
        if emails and getattr(settings, "EMAIL_HOST", ""):
            send_mail(f"FloBrain Pulse: {LABELS[rule.metric]}", text, None, emails, fail_silently=True)
    return fired
