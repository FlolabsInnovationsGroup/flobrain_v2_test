"""People talking to their buddies from WhatsApp or Telegram, and answering approvals by reply.

Only a linked, active member reaches a buddy. ``approve ABC123`` / ``reject ABC123`` decide one of
*that person's own* pending approvals through ``actions.service`` (which re-checks the person's
permissions now); nobody can decide someone else's approval from a phone.
"""

import re

from django.conf import settings

from channels import voice
from channels.models import ChannelLink
from organizations.flags import effective_flag
from organizations.models import OrgMembership
from organizations.permissions import can
from organizations.services.core import audit

DECISION = re.compile(r"^\s*(approve|reject|yes|no|وافق|ارفض|onayla|reddet|approuver|rejeter|aprovar|rejeitar)\s+#?([A-Za-z0-9]{6,12})\s*[.!]?\s*$", re.IGNORECASE)
APPROVE_WORDS = {"approve", "yes", "وافق", "onayla", "approuver", "aprovar"}
UNLINK = re.compile(r"^\s*(unlink|stop linking|الغاء الربط|إلغاء الربط)\s*$", re.IGNORECASE)


def short_code(proposal) -> str:
    return proposal.id.hex[:6].upper()


def _buddy_for(connection, user, org):
    from buddies.services import visible_buddies

    visible = visible_buddies(user, org)
    if connection.team_buddy_id and visible.filter(pk=connection.team_buddy_id).exists():
        return connection.team_buddy
    return visible.filter(is_builtin=True).order_by("name").first() or visible.order_by("name").first()


def _chat_for(link, buddy, user, org):
    from brain.models import Chat

    chat = link.chat
    if chat is None or chat.buddy_id != buddy.id or chat.user_id != user.id:
        label = "WhatsApp" if link.connection.kind == "whatsapp" else "Telegram"
        chat = Chat.objects.create(user=user, org=org, buddy=buddy, title=f"{buddy.name} on {label}"[:255])
        ChannelLink.objects.filter(pk=link.pk).update(chat=chat)
        link.chat = chat
    return chat


def decide(link, verb: str, code: str) -> str:
    from actions.models import ActionProposal
    from actions.service import ActionDenied, approve, reject

    user, org = link.user, link.org
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    if not effective_flag(org, membership, "ai_actions", default=False):
        return "Approvals are switched off for you."
    code = code.upper()
    # Only this person's own pending approvals: the same rule as the approvals page.
    pending = ActionProposal.objects.filter(org=org, user=user, status=ActionProposal.STATUS_PROPOSED).only("id", "summary")
    matches = [p for p in pending if p.id.hex.upper().startswith(code)]
    if not matches:
        return f"No approval {code} is waiting for you."
    if len(matches) > 1:
        return f"More than one approval starts with {code}. Open FloBrain to decide."
    proposal = matches[0]
    approving = verb.lower() in APPROVE_WORDS
    try:
        proposal = approve(proposal.id, user, org) if approving else reject(proposal.id, user, org)
    except ActionDenied as exc:
        return {
            "expired": f"Approval {code} has expired.",
            "not_pending": f"Approval {code} was already decided.",
            "permission": "You can't run this action any more.",
            "not_found": "You can't run this action any more.",
        }.get(exc.code, f"Approval {code} could not run.")
    audit(user, "channels.approval_reply", target=proposal, payload={"decision": "approve" if approving else "reject", "channel": link.connection.kind}, org=org)
    if not approving:
        return f"Rejected: {proposal.summary}"
    if proposal.status == ActionProposal.STATUS_EXECUTED:
        return f"Done: {proposal.summary}"
    return f"Approved, but it failed: {proposal.error or 'error'}"


def handle(connection, link, event) -> str:
    """Answer one message from a linked person. Returns the reply text."""
    user, org = link.user, link.org
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    if membership is None or not membership.is_active_member:
        ChannelLink.objects.filter(pk=link.pk).update(status=ChannelLink.REVOKED)
        return "This phone is no longer linked to FloBrain."
    if not effective_flag(org, membership, "channels", default=False):
        return "FloBrain on WhatsApp and Telegram is switched off for you."
    text = (event.text or "").strip()
    if (event.media or {}).get("type") == "voice":
        text = (voice.transcribe_inbound(connection, event.media) or "").strip()
        if not text:
            return "I can't listen to voice notes yet. Please type your message."
    if not text:
        return "Send a text message and your buddy will answer."
    if UNLINK.match(text):
        ChannelLink.objects.filter(pk=link.pk).update(status=ChannelLink.REVOKED)
        audit(user, "channels.unlink", target=link, payload={"channel": connection.kind, "from": "phone"}, org=org)
        return "Unlinked. Messages from here no longer reach your buddy."
    match = DECISION.match(text)
    if match:
        return decide(link, match.group(1), match.group(2))
    if not (can(user, "ai.use", org) and effective_flag(org, membership, "buddies", default=False)):
        return "Buddies are not available for you."
    max_chars = int(settings.FLOBRAIN_V2.get("AI_MAX_INPUT_CHARS", 8000))
    text = text[:max_chars]
    buddy = _buddy_for(connection, user, org)
    if buddy is None:
        return "You have no buddy to talk to yet."
    chat = _chat_for(link, buddy, user, org)
    from brain.models import Message
    from buddies.chat import run_buddy_turn

    status, body = run_buddy_turn(user, org, chat, text, {})
    if status != 200:
        return "Your buddy can't answer right now. Try again later."
    chat.save(update_fields=["updated_at"])
    answer = chat.messages.filter(role=Message.ROLE_ASSISTANT).order_by("-created_at", "-id").values_list("text", flat=True).first() or ""
    lines = [answer.strip()]
    from actions.models import ActionProposal

    for item in body.get("proposals") or []:
        proposal = ActionProposal.objects.filter(pk=item.get("id"), user=user).first()
        if proposal is not None:
            code = short_code(proposal)
            lines.append(f'Waiting for your approval: {proposal.summary}\nReply "approve {code}" or "reject {code}".')
    return "\n\n".join(line for line in lines if line)
