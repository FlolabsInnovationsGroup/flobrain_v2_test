"""Customer conversations: receive, let the customer buddy answer (or draft), hand off, deliver.

AI answers go out only when an admin turned on auto reply; otherwise they wait as drafts that a
person with ``customers.reply`` approves, edits or rejects. Staff replies and approved drafts are
delivered through the conversation's channel (the website chat reads them from FloBrain).
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from channels import customer_buddy, providers, voice
from channels.models import (
    ChannelConnection,
    CustomerConversation,
    CustomerMessage,
    CustomerSettings,
)

HANDOFF = "Thanks. I'm passing you to a person on our team. They'll reply here soon."
VOICE_PLACEHOLDER = "(voice note)"
WHATSAPP_WINDOW = timedelta(hours=24)
REASON_TEXT = {
    "asked_for_human": "the customer asked for a person",
    "blocked_topic": "the message is about a topic the buddy must not answer",
    "unsure": "the buddy was not sure",
    "ai_unavailable": "AI is not available",
    "voice_note": "the customer sent a voice note",
}


def settings_for(org) -> CustomerSettings:
    row, _ = CustomerSettings.objects.get_or_create(org=org)
    return row


def staff_for(conversation) -> list:
    """Who hears about this conversation: the assignee, else people in its room who handle customers."""
    from organizations.models import OrgMembership
    from organizations.permissions import can

    if conversation.assignee_id:
        return [conversation.assignee]
    members = OrgMembership.objects.filter(org=conversation.org, employment_status="active").select_related("user")
    if conversation.assigned_room_id:
        from rooms.services import user_can_access_room

        people = [m.user for m in members if user_can_access_room(m.user, conversation.assigned_room)]
        return [u for u in people if can(u, "customers.reply", conversation.org) or can(u, "customers.view", conversation.org)][:50]
    return [m.user for m in members if can(m.user, "customers.view", conversation.org)][:50]


def deliver(message: CustomerMessage) -> str:
    """Send a sent message through the channel. Records and returns the error code ("" when sent)."""
    conversation = message.conversation
    connection = conversation.connection
    error = ""
    if conversation.channel == ChannelConnection.WHATSAPP and not connection.demo:
        last = conversation.last_customer_at
        if last is None or timezone.now() - last > WHATSAPP_WINDOW:
            error = "outside_24h_window"  # needs an approved template message (not built yet)
    if not error:
        error = providers.send(connection, conversation.external_id, message.text)
    if error:
        CustomerMessage.objects.filter(pk=message.pk).update(status=CustomerMessage.FAILED, delivery_error=error[:60])
        message.status, message.delivery_error = CustomerMessage.FAILED, error[:60]
    return error


def _add(conversation, role, text, status=CustomerMessage.SENT, **extra) -> CustomerMessage:
    message = CustomerMessage.objects.create(conversation=conversation, role=role, text=text, status=status, **extra)
    CustomerConversation.objects.filter(pk=conversation.pk).update(last_message_at=message.created_at)
    conversation.last_message_at = message.created_at
    return message


def escalate(conversation, reason: str, settings_row=None, notify_customer=True):
    """Hand the conversation to a person: post in the chosen room, notify, tell the customer."""
    from notifications.services import notify

    settings_row = settings_row or settings_for(conversation.org)
    conversation.status, conversation.mode, conversation.escalation_reason = (
        CustomerConversation.WAITING_HUMAN,
        CustomerConversation.MODE_HUMAN,
        reason[:40],
    )
    if conversation.assigned_room_id is None and settings_row.escalation_room_id:
        conversation.assigned_room_id = settings_row.escalation_room_id
    conversation.save(update_fields=["status", "mode", "escalation_reason", "assigned_room"])
    room = conversation.assigned_room
    author = settings_row.updated_by
    if room is not None and author is not None:
        from rooms.models import RoomMessage
        from rooms.services import user_can_access_room

        if user_can_access_room(author, room):
            RoomMessage.objects.create(
                room=room,
                author=author,
                body=(
                    f"Customer buddy: {conversation.customer_name or 'A customer'} on {conversation.get_channel_display()} "
                    f"needs a person ({REASON_TEXT.get(reason, reason)}). Open Customers to reply."
                ),
            )
    notify(
        conversation.org,
        staff_for(conversation),
        "customer.escalated",
        {"text": f"{conversation.customer_name or 'A customer'} needs a person", "conversation": str(conversation.id), "reason": reason},
        link=f"customers?c={conversation.id}",
        push=True,
        push_title="A customer needs a person",
    )
    if notify_customer:
        message = _add(conversation, CustomerMessage.SYSTEM, HANDOFF)
        deliver(message)


def _notify_staff(conversation, text):
    from notifications.services import notify

    notify(conversation.org, staff_for(conversation), "customer.message", {"text": text[:120], "conversation": str(conversation.id)}, link=f"customers?c={conversation.id}")


def find_or_open(connection, external_id: str, name: str, contact_masked: str) -> CustomerConversation:
    conversation = (
        CustomerConversation.objects.filter(connection=connection, external_id=external_id).order_by("-last_message_at").first()
        if external_id
        else None
    )
    if conversation is None:
        conversation = CustomerConversation.objects.create(
            org=connection.org,
            connection=connection,
            channel=connection.kind,
            external_id=external_id,
            customer_name=(name or "")[:80],
            contact_masked=contact_masked[:40],
            demo=connection.demo,
        )
    return conversation


def receive(conversation, text: str, media: dict | None = None) -> CustomerMessage:
    """Store one customer message and let the buddy answer, draft, or hand off."""
    media = media or {}
    settings_row = settings_for(conversation.org)
    now = timezone.now()
    with transaction.atomic():
        conversation = CustomerConversation.objects.select_for_update().get(pk=conversation.pk)
        if conversation.status == CustomerConversation.RESOLVED:
            conversation.status, conversation.mode, conversation.escalation_reason = CustomerConversation.OPEN, CustomerConversation.MODE_BUDDY, ""
        conversation.last_customer_at = now
        conversation.save(update_fields=["status", "mode", "escalation_reason", "last_customer_at"])
        incoming = _add(conversation, CustomerMessage.CUSTOMER, (text or "").strip()[:4000] or VOICE_PLACEHOLDER, media=media)
    if conversation.mode == CustomerConversation.MODE_HUMAN:
        _notify_staff(conversation, incoming.text)
        return incoming
    if media.get("type") == "voice" and not (text or "").strip():
        transcript = voice.transcribe_inbound(conversation.connection, media)
        if not transcript:
            escalate(conversation, "voice_note", settings_row)
            return incoming
        text = transcript
    if not (text or "").strip():
        return incoming
    outcome = customer_buddy.answer(conversation, text, settings_row)
    if outcome.kind == "escalate":
        escalate(conversation, outcome.reason, settings_row)
        return incoming
    if settings_row.auto_reply:
        reply = _add(conversation, CustomerMessage.BUDDY, outcome.text, citations=outcome.citations)
        deliver(reply)
    else:
        _add(conversation, CustomerMessage.BUDDY, outcome.text, status=CustomerMessage.DRAFT, citations=outcome.citations)
        _notify_staff(conversation, f"Draft reply waiting: {outcome.text}")
    return incoming


# --- staff actions ----------------------------------------------------------------------------


def staff_reply(conversation, user, text: str) -> CustomerMessage:
    message = _add(conversation, CustomerMessage.STAFF, text, author=user)
    updates = {"mode": CustomerConversation.MODE_HUMAN, "status": CustomerConversation.OPEN}
    if conversation.assignee_id is None:
        updates["assignee"] = user
    CustomerConversation.objects.filter(pk=conversation.pk).update(**updates)
    # A person is answering now: drafts the buddy left behind are dropped.
    conversation.messages.filter(status=CustomerMessage.DRAFT).update(status=CustomerMessage.REJECTED)
    deliver(message)
    return message


def approve_draft(message, user, text: str | None = None) -> CustomerMessage:
    updated = CustomerMessage.objects.filter(pk=message.pk, status=CustomerMessage.DRAFT).update(
        status=CustomerMessage.SENT, approved_by=user, text=(text or message.text)[:4000]
    )
    if not updated:
        return None
    message.refresh_from_db()
    deliver(message)
    return message


def reject_draft(message, user) -> bool:
    return bool(CustomerMessage.objects.filter(pk=message.pk, status=CustomerMessage.DRAFT).update(status=CustomerMessage.REJECTED, approved_by=user))
