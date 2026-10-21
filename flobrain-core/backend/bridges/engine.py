"""What happens after Slack or Teams delivered something: store once, then answer on the jobs queue.

Rules:
- Only an ``active`` link (confirmed by the person inside FloBrain) reaches a buddy, and the buddy runs
  as that person (``run_buddy_turn`` / ``flo_turn``): their buddies, their sources, their tools.
- Someone not linked gets a short private notice. When their Slack or Teams email matches an active
  member, a ``pending`` link is suggested and the member confirms it in FloBrain. Never linked silently.
- Proposed actions become an approval message in the person's direct messages, never in a channel.
  Only that person can decide it, and ``actions.service`` re-checks their access when they do.
- Answers go back where the person asked: the Slack thread, the slash command (only to them), the DM,
  or the Teams conversation. Nothing is posted anywhere else.
"""

import contextlib
import contextvars
import hashlib
import logging
import re
import threading
import time

from django.conf import settings
from django.db import IntegrityError, close_old_connections, transaction
from django.utils import timezone

from bridges import slack, teams
from bridges.models import (
    SLACK,
    TEAMS,
    BridgeCard,
    BridgeEvent,
    BridgeLink,
    BridgeThread,
    BridgeWorkspace,
)
from channels import ratelimit
from jobs.queue import enqueue, register
from organizations.flags import effective_flag
from organizations.models import OrgMembership
from organizations.permissions import can
from organizations.services.core import audit

logger = logging.getLogger(__name__)

JOB = "bridges.process"
MIRROR_JOB = "bridges.mirror_proposal"
PLATFORM_LABEL = {SLACK: "Slack", TEAMS: "Teams"}
HELP = re.compile(r"^\s*(help|\?)\s*$", re.IGNORECASE)
UNLINK = re.compile(r"^\s*unlink\s*$", re.IGNORECASE)

_in_bridge_turn: contextvars.ContextVar = contextvars.ContextVar("bridges_in_turn", default=False)


def limit(name: str, default: int) -> int:
    return int((getattr(settings, "BRIDGES_LIMITS", None) or {}).get(name, default))


def bridge_turn_active() -> bool:
    return bool(_in_bridge_turn.get())


@contextlib.contextmanager
def _bridge_turn():
    token = _in_bridge_turn.set(True)
    try:
        yield
    finally:
        _in_bridge_turn.reset(token)


# --- store and dispatch -----------------------------------------------------------------------


def record(workspace, item: dict, kind: str = BridgeEvent.MESSAGE) -> BridgeEvent | None:
    """One row per platform event id. Returns None for a repeated delivery (Slack retries)."""
    try:
        with transaction.atomic():
            return BridgeEvent.objects.create(
                org_id=workspace.org_id,
                workspace=workspace,
                event_id=str(item["id"])[:128],
                kind=item.get("kind") or kind,
                sender=str(item.get("sender") or "")[:64],
                sender_name=str(item.get("sender_name") or "")[:120],
                text=str(item.get("text") or "")[:4000],
                context=item.get("context") or {},
            )
    except IntegrityError:
        return None


def _run_detached(fn, *args):
    def run():
        try:
            fn(*args)
        finally:
            close_old_connections()

    threading.Thread(target=run, daemon=True).start()


def dispatch(event) -> None:
    """Queue the work so the platform gets its answer at once (Slack wants one within 3 seconds)."""
    result = enqueue(JOB, {"event": str(event.id)})
    if isinstance(result, dict) and result.get("reason") == "unavailable":
        # No worker deployed: work in the background (after the row is committed), never inline.
        transaction.on_commit(lambda: _run_detached(process, event.id))


@register(JOB)
def process_job(payload):
    return process(payload.get("event"))


def _finish(event, status, outcome):
    context = dict(event.context or {})
    context.pop("response_url", None)  # a short-lived capability: not kept after use
    BridgeEvent.objects.filter(pk=event.pk).update(status=status, outcome=outcome[:40], context=context)
    return outcome


def process(event_id) -> str:
    if not BridgeEvent.objects.filter(pk=event_id, status=BridgeEvent.RECEIVED).update(status=BridgeEvent.WORKING):
        return "already_processed"
    event = BridgeEvent.objects.select_related("workspace", "workspace__org").get(pk=event_id)
    workspace, org = event.workspace, event.workspace.org
    if workspace.status != BridgeWorkspace.ACTIVE or not org.is_active or not effective_flag(org, None, "bridges", default=False):
        return _finish(event, BridgeEvent.IGNORED, "bridge_off")
    if workspace.platform == TEAMS:
        _remember_teams(workspace, event)
    try:
        if event.kind == BridgeEvent.DECISION:
            return _finish(event, BridgeEvent.DONE, decide(workspace, org, event))
        return _finish(event, BridgeEvent.DONE, _message(workspace, org, event))
    except Exception:
        logger.exception("bridges: event %s failed", event.id)
        return _finish(event, BridgeEvent.FAILED, "error")


# --- answering --------------------------------------------------------------------------------


def answer(workspace, event, text: str) -> None:
    """Reply where the person asked: the thread, only to them for a slash command, or the DM."""
    ctx = event.context or {}
    if workspace.platform == SLACK:
        kind = ctx.get("channel_type")
        if kind == "command":
            if ctx.get("response_url") or workspace.demo:
                slack.respond(workspace, ctx.get("response_url", ""), text)
            elif ctx.get("channel"):
                slack.ephemeral(workspace, ctx["channel"], event.sender, text)
        elif kind == "channel":
            slack.post(workspace, ctx["channel"], text, thread_ts=ctx.get("thread_ts") or ctx.get("ts", ""))
        else:
            slack.post(workspace, ctx["channel"], text, thread_ts=ctx.get("thread_ts", ""))
    else:
        teams.reply(workspace, ctx, text)


def notice(workspace, event, text: str) -> None:
    """A private note to the sender (ephemeral in Slack channels)."""
    ctx = event.context or {}
    if workspace.platform == SLACK and ctx.get("channel_type") in ("channel", "action"):
        slack.ephemeral(workspace, ctx["channel"], event.sender, text)
    else:
        answer(workspace, event, text)


def active_link(workspace, sender: str):
    return BridgeLink.objects.filter(workspace=workspace, status=BridgeLink.ACTIVE, external_id=sender).select_related("user").first()


def _remember_teams(workspace, event):
    """Keep where to reach this person directly (their 1:1 chat with the bot)."""
    ctx = event.context or {}
    if not ctx.get("service_url") or not teams.service_url_ok(ctx["service_url"]):
        return
    for link in BridgeLink.objects.filter(workspace=workspace, external_id=event.sender).exclude(status=BridgeLink.REVOKED):
        config = dict(link.config or {})
        config.update({"service_url": ctx["service_url"], "teams_user": ctx.get("teams_user", ""), "bot": ctx.get("bot", ""), "tenant": ctx.get("tenant", "")})
        if ctx.get("conversation_type") == "personal":
            config["conversation"] = ctx.get("conversation", "")
        if config != link.config:
            BridgeLink.objects.filter(pk=link.pk).update(config=config)


def _unlinked(workspace, org, event) -> str:
    label = PLATFORM_LABEL[workspace.platform]
    if not ratelimit.hit("bridge-unlinked", f"{workspace.id}:{event.sender}", limit("unlinked_notices", 1), 600):
        return "not_linked:quiet"
    profile = slack.user_profile(workspace, event.sender) if workspace.platform == SLACK else teams.member_profile(workspace, event.context or {})
    member = match_member(org, profile.get("email", "")) if profile else None
    if member is not None and (workspace.platform == SLACK or profile.get("id") in ("", event.sender)):
        suggest(workspace, member.user, event.sender, profile, BridgeLink.FROM_PLATFORM, event.context or {})
        notice(
            workspace,
            event,
            f"Almost there. To keep your FloBrain data private, confirm this {label} account once in FloBrain: Settings, Bridges, Confirm. Then ask me again.",
        )
        return "not_linked:suggested"
    notice(workspace, event, f"Your {label} account is not linked to FloBrain. Open FloBrain, Settings, Bridges, and press Link my {label}.")
    return "not_linked"


def match_member(org, email: str):
    """The active membership whose FloBrain email is exactly this address, or None."""
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return None
    rows = list(OrgMembership.objects.filter(org=org, user__email__iexact=email, employment_status="active").select_related("user")[:2])
    return rows[0] if len(rows) == 1 else None


def mask_email(email: str) -> str:
    if "@" not in (email or ""):
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:1]}•••@{domain}"[:120]


def suggest(workspace, user, external_id: str, profile: dict, found_via: str, context: dict | None = None):
    """A pending link the person confirms in FloBrain. Replaces older pending suggestions for them."""
    from notifications.services import notify

    if BridgeLink.objects.filter(workspace=workspace, user=user, status=BridgeLink.ACTIVE, external_id=external_id).exists():
        return None
    BridgeLink.objects.filter(workspace=workspace, user=user, status=BridgeLink.PENDING).update(status=BridgeLink.REVOKED)
    config = {}
    if workspace.platform == TEAMS and context:
        config = {k: context.get(k, "") for k in ("service_url", "teams_user", "bot", "tenant")}
        if context.get("conversation_type") == "personal":
            config["conversation"] = context.get("conversation", "")
    link = BridgeLink.objects.create(
        org=workspace.org,
        user=user,
        workspace=workspace,
        status=BridgeLink.PENDING,
        external_id=external_id,
        external_name=(profile or {}).get("name", "")[:120],
        email_masked=mask_email((profile or {}).get("email", "")),
        found_via=found_via,
        config=config,
    )
    if found_via == BridgeLink.FROM_PLATFORM:
        label = PLATFORM_LABEL[workspace.platform]
        notify(
            workspace.org,
            [user],
            "bridges.link_pending",
            {"text": f"Confirm your {label} account to use FloBrain there", "platform": workspace.platform},
            link="settings/bridges",
        )
    return link


def _thread_key(workspace, event) -> str:
    ctx = event.context or {}
    if workspace.platform == SLACK:
        if ctx.get("channel_type") == "channel":
            key = f"{ctx.get('channel')}:{ctx.get('thread_ts') or ctx.get('ts')}"
        elif ctx.get("channel_type") == "command":
            key = f"cmd:{ctx.get('channel', '')}"
        else:
            key = f"{ctx.get('channel')}:{ctx.get('thread_ts', '')}"
    else:
        key = f"teams:{ctx.get('conversation', '')}"
    return key if len(key) <= 200 else hashlib.sha256(key.encode()).hexdigest()


def _chat(link, buddy, key, platform):
    from brain.models import Chat

    row = BridgeThread.objects.filter(link=link, buddy=buddy, thread_key=key).select_related("chat").first()
    if row is not None and row.chat.user_id == link.user_id:
        return row.chat
    chat = Chat.objects.create(user=link.user, org=link.org, buddy=buddy, title=f"{buddy.name} on {PLATFORM_LABEL[platform]}"[:255])
    BridgeThread.objects.update_or_create(link=link, buddy=buddy, thread_key=key, defaults={"chat": chat})
    return chat


def _named(text: str, buddies) -> tuple:
    """A buddy the person named at the start ("ask Finance Buddy: ...", "Legal, ..."), and the rest."""
    lowered = text.lower()
    options = []
    for buddy in buddies:
        for name in {buddy.name.lower(), buddy.slug.lower().replace("-", " ")}:
            if len(name) >= 3:
                options.append((name, buddy))
    for name, buddy in sorted(options, key=lambda o: -len(o[0])):
        for prefix in (f"ask {name}", f"@{name}", name):
            if lowered.startswith(prefix):
                rest = text[len(prefix):]
                if not rest or rest[0] in ":,-— \n":
                    return buddy, rest.lstrip(":,-— \n").strip()
    return None, text


def choose_buddy(workspace, user, org, text) -> tuple:
    """(buddy, text). Named buddy first; then the workspace default; then Flo when on; then the first built-in."""
    from buddies.router import NEVER_ROUTE, flo_on, is_flo
    from buddies.services import visible_buddies
    from buddies.templates_extra import ensure_flo

    visible = visible_buddies(user, org)
    flo = flo_on(org, user)
    nameable = [b for b in visible.order_by("name") if b.slug not in NEVER_ROUTE]
    buddy, rest = _named(text, nameable)
    if buddy is not None and rest:
        return buddy, rest
    if workspace.default_buddy_id:
        chosen = visible.filter(pk=workspace.default_buddy_id).first()
        if chosen is not None and (not is_flo(chosen) or flo):
            return chosen, text
    if flo:
        return ensure_flo(org), text
    pool = visible.exclude(slug__in=NEVER_ROUTE)
    return (pool.filter(is_builtin=True).order_by("name").first() or pool.order_by("name").first()), text


def run_turn(link, buddy, text, key, platform) -> tuple[int, dict, str]:
    """Run one buddy turn as the linked person. Returns (status, body, answer text)."""
    from brain.models import Message
    from buddies.chat import run_buddy_turn
    from buddies.router import flo_turn, is_flo, record_answer

    chat = _chat(link, buddy, key, platform)
    started = time.monotonic()
    with _bridge_turn():
        if is_flo(buddy):
            status, body = flo_turn(link.user, link.org, chat, text, {})
        else:
            status, body = run_buddy_turn(link.user, link.org, chat, text, {})
            if status == 200:
                record_answer(link.org, buddy, chat, int((time.monotonic() - started) * 1000), body.get("citations"))
    if status != 200:
        return status, body, ""
    chat.save(update_fields=["updated_at"])
    reply = chat.messages.filter(role=Message.ROLE_ASSISTANT).order_by("-created_at", "-id").values_list("text", flat=True).first() or ""
    return status, body, reply.strip()


def help_text(platform: str) -> str:
    label = PLATFORM_LABEL[platform]
    how = "mention @FloBrain in a channel, write to me directly, or type /flo and your question" if platform == SLACK else "mention FloBrain in a channel or write to me in a chat"
    return (
        f"Ask your FloBrain buddies from {label}: {how}. "
        "Start with a buddy's name to ask that buddy, like \"Finance Buddy: what is left in the Q3 budget?\". "
        "Actions your buddy proposes come to you here for approval. Send \"unlink\" to disconnect."
    )


def _message(workspace, org, event) -> str:
    link = active_link(workspace, event.sender)
    if link is None:
        return _unlinked(workspace, org, event)
    user = link.user
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    if membership is None or not membership.is_active_member:
        BridgeLink.objects.filter(pk=link.pk).update(status=BridgeLink.REVOKED)
        notice(workspace, event, "This account is no longer linked to FloBrain.")
        return "member_inactive"
    if not effective_flag(org, membership, "bridges", default=False):
        notice(workspace, event, "FloBrain in Slack and Teams is switched off for you.")
        return "flag_off"
    text = (event.text or "").strip()
    if UNLINK.match(text):
        BridgeLink.objects.filter(pk=link.pk).update(status=BridgeLink.REVOKED)
        audit(user, "bridges.unlink", target=link, payload={"platform": workspace.platform, "from": "platform"}, org=org)
        notice(workspace, event, "Unlinked. Your messages here no longer reach FloBrain.")
        return "unlinked"
    if not text or HELP.match(text):
        notice(workspace, event, help_text(workspace.platform))
        return "help"
    if not ratelimit.hit("bridge-turn", str(link.id), limit("turns_per_minute", 10), 60):
        notice(workspace, event, "You are asking very fast. Wait a minute and try again.")
        return "rate_limited"
    if not (can(user, "ai.use", org) and effective_flag(org, membership, "buddies", default=False)):
        notice(workspace, event, "Buddies are not available for you.")
        return "no_ai"
    text = text[: int(settings.FLOBRAIN_V2.get("AI_MAX_INPUT_CHARS", 8000))]
    buddy, text = choose_buddy(workspace, user, org, text)
    if buddy is None:
        notice(workspace, event, "You have no buddy to talk to yet.")
        return "no_buddy"
    status, body, reply = run_turn(link, buddy, text, _thread_key(workspace, event), workspace.platform)
    if status != 200:
        notice(workspace, event, "Your buddy can't answer right now. Try again later.")
        return f"turn:{status}"
    from actions.models import ActionProposal

    proposals = [p for p in (ActionProposal.objects.filter(pk=item.get("id"), user=user, org=org).first() for item in body.get("proposals") or []) if p is not None]
    lines = [reply or "Done."]
    in_dm = (event.context or {}).get("channel_type") == "im" or (event.context or {}).get("conversation_type") == "personal"
    if proposals and not in_dm:
        lines.append(f"{len(proposals)} action(s) wait for your approval. I sent them to you in a direct message.")
    answer(workspace, event, "\n\n".join(lines))
    for proposal in proposals:
        send_card(workspace, link, proposal, buddy.name, event.context or {})
    return f"answered:{len(proposals)}"


# --- approvals --------------------------------------------------------------------------------


def _slack_dm(workspace, link) -> str:
    channel = (link.config or {}).get("dm_channel", "")
    if not channel:
        channel = slack.open_dm(workspace, link.external_id)
        if channel:
            BridgeLink.objects.filter(pk=link.pk).update(config={**(link.config or {}), "dm_channel": channel})
            link.config = {**(link.config or {}), "dm_channel": channel}
    return channel


def _teams_dm(workspace, link, context: dict | None = None) -> tuple[str, str]:
    config = {**(link.config or {})}
    for key in ("service_url", "teams_user", "bot", "tenant"):
        if not config.get(key) and (context or {}).get(key):
            config[key] = context[key]
    if (context or {}).get("conversation_type") == "personal" and context.get("conversation"):
        config["conversation"] = context["conversation"]
    service_url = config.get("service_url", "")
    if not config.get("conversation") and service_url and config.get("teams_user"):
        config["conversation"] = teams.open_personal(workspace, service_url, config.get("bot", ""), config["teams_user"], config.get("tenant", ""))
    if config != (link.config or {}):
        BridgeLink.objects.filter(pk=link.pk).update(config=config)
        link.config = config
    return service_url, config.get("conversation", "")


def send_dm(workspace, link, text: str) -> bool:
    if workspace.platform == SLACK:
        channel = _slack_dm(workspace, link)
        return bool(channel) and bool(slack.post(workspace, channel, text).get("ok"))
    service_url, conversation = _teams_dm(workspace, link)
    return bool(conversation) and bool(teams.send_to(workspace, service_url, conversation, text).get("ok"))


def send_card(workspace, link, proposal, buddy_name: str, context: dict | None = None):
    """Post the approval message to the person's direct messages and remember it."""
    if workspace.platform == SLACK:
        channel = _slack_dm(workspace, link)
        if not channel:
            return None
        blocks = slack.approval_blocks(proposal, buddy_name)
        result = slack.post(workspace, channel, f"Waiting for your approval: {proposal.summary}", blocks=blocks)
        if not result.get("ok"):
            return None
        return BridgeCard.objects.create(
            org=workspace.org, workspace=workspace, link=link, proposal=proposal, channel=channel,
            message_id=str(result.get("ts") or "")[:200], payload={"blocks": blocks},
        )
    service_url, conversation = _teams_dm(workspace, link, context)
    if not conversation:
        return None
    attachments = teams.approval_card(proposal, buddy_name)
    result = teams.send_to(workspace, service_url, conversation, "", attachments)
    if not result.get("ok"):
        return None
    return BridgeCard.objects.create(
        org=workspace.org, workspace=workspace, link=link, proposal=proposal, channel=conversation,
        message_id=result.get("id", "")[:200], service_url=service_url[:300], payload={"attachments": attachments},
    )


DENIED = {
    "expired": "This approval has expired.",
    "not_pending": "This was already decided.",
    "permission": "You can't run this action any more.",
    "not_found": "Only the person this approval is for can decide it.",
    "not_available": "This action is switched off.",
    "invalid": "This action is no longer valid.",
}


def _find_card(workspace, event):
    ctx = event.context or {}
    cards = BridgeCard.objects.filter(workspace=workspace, proposal_id=_uuid(ctx.get("proposal"))).select_related("proposal", "link", "link__user")
    if workspace.platform == SLACK:
        return cards.filter(channel=ctx.get("channel", ""), message_id=ctx.get("ts", "")).first()
    if ctx.get("card_activity"):
        return cards.filter(message_id=ctx["card_activity"]).first()
    return cards.filter(channel=ctx.get("conversation", "")).order_by("-created_at").first()


def _uuid(value):
    import uuid

    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def update_card(workspace, card, result_text: str) -> None:
    proposal = card.proposal
    if workspace.platform == SLACK:
        blocks = slack.decided_blocks(proposal, result_text)
        slack.update(workspace, card.channel, card.message_id, f"{result_text}: {proposal.summary}", blocks)
        card.payload = {"blocks": blocks}
    else:
        attachments = teams.decided_card(proposal, result_text)
        teams.update(workspace, card.service_url, card.channel, card.message_id, attachments)
        card.payload = {"attachments": attachments}
    card.status = "decided"
    card.save(update_fields=["status", "payload"])


def decide(workspace, org, event) -> str:
    """Approve or reject from a button. Only the proposal's own person, re-checked by actions.service."""
    from actions.models import ActionProposal
    from actions.service import ActionDenied, approve, reject

    card = _find_card(workspace, event)
    if card is None:
        notice(workspace, event, "I can't find this approval. Open FloBrain, Approvals.")
        return "decision:unknown_card"
    link = active_link(workspace, event.sender)
    if link is None:
        notice(workspace, event, "Your account is not linked to FloBrain, so you can't decide approvals here.")
        return "decision:not_linked"
    if card.link.user_id != link.user_id or card.proposal.user_id != link.user_id:
        notice(workspace, event, DENIED["not_found"])
        return "decision:not_yours"
    user = link.user
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    if membership is None or not membership.is_active_member or not effective_flag(org, membership, "bridges", default=False):
        notice(workspace, event, "FloBrain in Slack and Teams is switched off for you.")
        return "decision:off"
    if not effective_flag(org, membership, "ai_actions", default=False):
        notice(workspace, event, "Approvals are switched off for you.")
        return "decision:actions_off"
    approving = event.text == "approve"
    try:
        proposal = approve(card.proposal_id, user, org) if approving else reject(card.proposal_id, user, org)
    except ActionDenied as exc:
        text = DENIED.get(exc.code, "This approval could not run.")
        if exc.code in ("expired", "not_pending"):
            card.proposal.refresh_from_db()
            update_card(workspace, card, text)
        else:
            notice(workspace, event, text)
        return f"decision:{exc.code}"
    audit(user, "bridges.approval", target=proposal, payload={"decision": "approve" if approving else "reject", "platform": workspace.platform}, org=org)
    card.proposal = proposal
    if not approving:
        result = "Rejected"
    elif proposal.status == ActionProposal.STATUS_EXECUTED:
        result = "Approved and done"
    else:
        result = f"Approved, but it failed: {proposal.error or 'error'}"
    update_card(workspace, card, result)
    return "decision:approved" if approving else "decision:rejected"


# --- approvals from elsewhere (FloBrain web, automations): mirrored to the person's DM ----------


def mirror_proposal(proposal_id) -> int:
    from actions.models import ActionProposal

    proposal = ActionProposal.objects.filter(pk=proposal_id, status=ActionProposal.STATUS_PROPOSED).select_related("org", "buddy").first()
    if proposal is None or not proposal.org.is_active or not effective_flag(proposal.org, None, "bridges", default=False):
        return 0
    membership = OrgMembership.objects.filter(org=proposal.org, user_id=proposal.user_id).first()
    if membership is None or not membership.is_active_member or not effective_flag(proposal.org, membership, "bridges", default=False):
        return 0
    sent = 0
    links = BridgeLink.objects.filter(org=proposal.org, user_id=proposal.user_id, status=BridgeLink.ACTIVE, mirror=True).select_related("workspace")
    for link in links:
        workspace = link.workspace
        if workspace.status != BridgeWorkspace.ACTIVE or not (workspace.mirror or {}).get("approvals"):
            continue
        if BridgeCard.objects.filter(workspace=workspace, proposal=proposal).exists():
            continue
        if send_card(workspace, link, proposal, proposal.buddy.name if proposal.buddy_id else "FloBrain") is not None:
            sent += 1
    return sent


@register(MIRROR_JOB)
def mirror_job(payload):
    return mirror_proposal(payload.get("proposal"))


def on_proposal_saved(sender, instance, created, **kwargs):
    """Signal receiver: a new proposal made outside a bridge turn may be mirrored to Slack or Teams."""
    if not created or bridge_turn_active() or kwargs.get("raw"):
        return
    proposal_id, user_id, org_id = str(instance.pk), instance.user_id, instance.org_id

    def later():
        if not BridgeLink.objects.filter(org_id=org_id, user_id=user_id, status=BridgeLink.ACTIVE, mirror=True).exists():
            return
        try:
            result = enqueue(MIRROR_JOB, {"proposal": proposal_id})
        except Exception:
            logger.exception("bridges: mirror enqueue failed")
            return
        if isinstance(result, dict) and result.get("reason") == "unavailable":
            _run_detached(mirror_proposal, proposal_id)

    transaction.on_commit(later)


# --- notices (automations, customer escalations): mirrored by ``tick_bridges`` -------------------

MIRROR_KINDS = {
    "automations": ("automation.notice", "automation.daily_brief", "automation.nudge"),
    "escalations": ("customer.escalated",),
}


def mirror_notifications(now=None, batch=200) -> int:
    from bridges.setup import frontend_base
    from notifications.models import Notification

    now = now or timezone.now()
    sent = 0
    for workspace in BridgeWorkspace.objects.filter(status=BridgeWorkspace.ACTIVE).select_related("org"):
        kinds = [k for key, values in MIRROR_KINDS.items() if (workspace.mirror or {}).get(key) for k in values]
        org = workspace.org
        cursor = workspace.mirror_cursor or workspace.created_at
        if not kinds or not org.is_active or not effective_flag(org, None, "bridges", default=False):
            BridgeWorkspace.objects.filter(pk=workspace.pk).update(mirror_cursor=now)
            continue
        links = {link.user_id: link for link in BridgeLink.objects.filter(workspace=workspace, status=BridgeLink.ACTIVE, mirror=True)}
        rows = list(
            Notification.objects.filter(org=org, kind__in=kinds, created_at__gt=cursor, created_at__lte=now, user_id__in=list(links)).order_by("created_at")[:batch]
        )
        for row in rows:
            payload = row.payload or {}
            title = str(payload.get("title") or "")[:120]
            text = str(payload.get("text") or row.kind)[:1500]
            path = str(payload.get("link") or "")
            url = f"{frontend_base()}/w/{org.slug}/{path}" if path and not path.startswith(("http:", "https:", "/")) else f"{frontend_base()}/w/{org.slug}"
            if send_dm(workspace, links[row.user_id], f"{title + ': ' if title else ''}{text}\n\nOpen in FloBrain: {url}"):
                sent += 1
        last = rows[-1].created_at if len(rows) == batch else now
        BridgeWorkspace.objects.filter(pk=workspace.pk).update(mirror_cursor=last)
    return sent
