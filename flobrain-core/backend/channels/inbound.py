"""Inbound provider messages: store once (idempotent on the provider message id), then process.

Processing runs on the jobs queue when a worker exists; otherwise inline (and always inline in
tests and DEBUG, where jobs are eager).
"""

import logging

from django.db import IntegrityError, transaction

from channels import customers, linking, providers, team
from channels.models import ChannelConnection, InboundEvent
from jobs.queue import enqueue, register
from organizations.flags import effective_flag

logger = logging.getLogger(__name__)

JOB = "channels.inbound"
PROCESSING = "working"

LINK_REPLIES = {
    "linked": "Linked. You can talk to your FloBrain buddy here now. Send \"unlink\" to stop.",
    "wrong": "That code is not right. Make a new code in FloBrain, Settings, Channels.",
    "expired": "That code has expired. Make a new code in FloBrain, Settings, Channels.",
    "locked": "Too many wrong codes. Try again in an hour.",
}


def record(connection, item: dict) -> InboundEvent | None:
    """Keep one row per provider message id. Returns None for a duplicate delivery."""
    try:
        with transaction.atomic():
            return InboundEvent.objects.create(
                org_id=connection.org_id,
                connection=connection,
                provider_message_id=str(item["id"])[:128],
                sender=str(item.get("sender") or "")[:64],
                sender_name=str(item.get("name") or "")[:120],
                text=str(item.get("text") or "")[:4000],
                media=item.get("media") or {},
            )
    except IntegrityError:
        return None


def dispatch(events) -> None:
    for event in events:
        result = enqueue(JOB, {"event": str(event.id)})
        if isinstance(result, dict) and result.get("reason") == "unavailable":
            process(event.id)  # no worker deployed: do it now rather than drop it


@register(JOB)
def process_job(payload):
    return process(payload.get("event"))


def _finish(event, status, outcome):
    InboundEvent.objects.filter(pk=event.pk).update(status=status, outcome=outcome[:40])
    return outcome


def process(event_id) -> str:
    # Claim the row so a retried job never handles the same message twice.
    if not InboundEvent.objects.filter(pk=event_id, status=InboundEvent.RECEIVED).update(status=PROCESSING):
        return "already_processed"
    event = InboundEvent.objects.select_related("connection", "connection__org").get(pk=event_id)
    connection = event.connection
    org = connection.org
    if connection.status != ChannelConnection.ACTIVE or not org.is_active or not effective_flag(org, None, "channels", default=False):
        return _finish(event, InboundEvent.IGNORED, "channel_off")
    try:
        return _route(connection, org, event)
    except Exception:
        logger.exception("channels: inbound %s failed", event.id)
        return _finish(event, InboundEvent.FAILED, "error")


def _route(connection, org, event) -> str:
    link = linking.active_link(connection, event.sender) if connection.serve_team else None
    if link is not None:
        reply = team.handle(connection, link, event)
        error = providers.send(connection, event.sender, reply) if reply else ""
        return _finish(event, InboundEvent.DONE, f"team{':' + error if error else ''}")
    if connection.serve_team and linking.is_code_attempt(event.text):
        outcome, _ = linking.redeem(connection, event.sender, event.sender_name, event.text)
        if outcome == "linked" or not connection.serve_customers:
            providers.send(connection, event.sender, LINK_REPLIES[outcome])
            return _finish(event, InboundEvent.DONE, f"link:{outcome}")
    customers_on = connection.serve_customers and effective_flag(org, None, "customer_buddy", default=False)
    if not customers_on:
        return _finish(event, InboundEvent.IGNORED, "not_linked")
    conversation = customers.find_or_open(connection, event.sender, event.sender_name, linking.mask(event.sender, connection.kind))
    customers.receive(conversation, event.text, event.media)
    return _finish(event, InboundEvent.DONE, "customer")
