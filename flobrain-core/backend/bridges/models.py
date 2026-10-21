"""Slack and Microsoft Teams bridges (growth round M2, flag ``bridges``).

A ``BridgeWorkspace`` binds one Slack workspace (team id) or one Microsoft 365 tenant to exactly
one FloBrain org. The Slack bot token is kept only as AES-256-GCM ciphertext bound to the row and
org (``integrations.crypto`` through ``channels.vault``); responses carry masked hints. Teams uses
the platform's Azure bot (app id and secret from the environment), so a Teams row holds no secret.

A ``BridgeLink`` ties a Slack user or an Entra ID (AAD) object id to one FloBrain member. It is
``pending`` until that member confirms it inside FloBrain; only ``active`` links reach a buddy.
"""

import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone

SLACK, TEAMS = "slack", "teams"
PLATFORM_CHOICES = [(SLACK, "Slack"), (TEAMS, "Microsoft Teams")]


def default_mirror():
    return {"approvals": True, "automations": False, "escalations": False}


class BridgeWorkspace(models.Model):
    NOT_SET_UP, ACTIVE, ERROR, DISCONNECTED = "not_set_up", "active", "error", "disconnected"
    LIVE = (ACTIVE, ERROR, NOT_SET_UP)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="bridge_workspaces")
    platform = models.CharField(max_length=8, choices=PLATFORM_CHOICES)
    # Slack team id (T0123) or the Microsoft 365 tenant id (a GUID).
    external_id = models.CharField(max_length=64)
    name = models.CharField(max_length=120, blank=True, default="")
    status = models.CharField(max_length=14, default=NOT_SET_UP)
    # Non-secret: Slack bot_user_id, app_id, scopes, url; Teams bot_id.
    config = models.JSONField(default=dict, blank=True)
    secrets_ciphertext = models.BinaryField(null=True, blank=True)
    key_version = models.PositiveSmallIntegerField(default=1)
    secret_hints = models.JSONField(default=dict, blank=True)
    # Empty: Flo when the flo_router flag is on for the person, else the first built-in buddy they can use.
    default_buddy = models.ForeignKey("buddies.Buddy", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    mirror = models.JSONField(default=default_mirror, blank=True)
    mirror_cursor = models.DateTimeField(null=True, blank=True)
    demo = models.BooleanField(default=False)
    last_error = models.CharField(max_length=120, blank=True, default="")
    last_checked_at = models.DateTimeField(null=True, blank=True)
    installed_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bridge_workspaces"
        constraints = [
            # A Slack workspace or Microsoft tenant belongs to one FloBrain org at a time.
            models.UniqueConstraint(
                fields=["platform", "external_id"], condition=~Q(status="disconnected"), name="bridge_workspace_one_org"
            )
        ]
        indexes = [models.Index(fields=["org", "platform"], name="bridge_ws_org_platform")]

    def __repr__(self):  # never the ciphertext
        return f"<BridgeWorkspace {self.platform} {self.id}>"


class BridgeLink(models.Model):
    PENDING, ACTIVE, REVOKED = "pending", "active", "revoked"
    FROM_PLATFORM, FROM_FLOBRAIN = "platform", "flobrain"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="bridge_links")
    workspace = models.ForeignKey(BridgeWorkspace, on_delete=models.CASCADE, related_name="links")
    status = models.CharField(max_length=8, default=PENDING)
    # Slack user id (U0123) or the Entra ID object id.
    external_id = models.CharField(max_length=64)
    external_name = models.CharField(max_length=120, blank=True, default="")
    email_masked = models.CharField(max_length=120, blank=True, default="")
    # How the match was found: the person wrote to the bot, or pressed "Link my Slack" in FloBrain.
    found_via = models.CharField(max_length=10, default=FROM_PLATFORM)
    # Slack DM channel; Teams user id (29:...), 1:1 conversation id and service URL for direct messages.
    config = models.JSONField(default=dict, blank=True)
    mirror = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bridge_links"
        indexes = [models.Index(fields=["workspace", "status", "external_id"], name="bridge_link_lookup")]


class BridgeThread(models.Model):
    """The FloBrain chat behind one Slack thread or Teams conversation, per buddy (keeps context)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    link = models.ForeignKey(BridgeLink, on_delete=models.CASCADE, related_name="threads")
    buddy = models.ForeignKey("buddies.Buddy", on_delete=models.CASCADE, related_name="+")
    thread_key = models.CharField(max_length=200)
    chat = models.ForeignKey("brain.Chat", on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "bridge_threads"
        constraints = [models.UniqueConstraint(fields=["link", "buddy", "thread_key"], name="unique_bridge_thread")]


class BridgeEvent(models.Model):
    """One inbound Slack event, slash command, button press or Teams activity, kept once."""

    RECEIVED, WORKING, DONE, IGNORED, FAILED = "received", "working", "done", "ignored", "failed"
    MESSAGE, COMMAND, DECISION = "message", "command", "decision"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    workspace = models.ForeignKey(BridgeWorkspace, on_delete=models.CASCADE, related_name="events")
    event_id = models.CharField(max_length=128)
    kind = models.CharField(max_length=10, default=MESSAGE)
    sender = models.CharField(max_length=64, blank=True, default="")
    sender_name = models.CharField(max_length=120, blank=True, default="")
    text = models.TextField(blank=True, default="")
    # Where to answer: Slack channel / thread_ts / channel_type; Teams service_url / conversation / activity id.
    context = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, default=RECEIVED)
    outcome = models.CharField(max_length=40, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "bridge_events"
        constraints = [models.UniqueConstraint(fields=["workspace", "event_id"], name="unique_bridge_event")]


class BridgeCard(models.Model):
    """An approval message FloBrain posted in Slack or Teams for one proposal."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    workspace = models.ForeignKey(BridgeWorkspace, on_delete=models.CASCADE, related_name="cards")
    link = models.ForeignKey(BridgeLink, on_delete=models.CASCADE, related_name="cards")
    proposal = models.ForeignKey("actions.ActionProposal", on_delete=models.CASCADE, related_name="+")
    # Slack: channel + ts. Teams: conversation + activity id + service_url.
    channel = models.CharField(max_length=200, blank=True, default="")
    message_id = models.CharField(max_length=200, blank=True, default="")
    service_url = models.CharField(max_length=300, blank=True, default="")
    status = models.CharField(max_length=10, default="waiting")
    payload = models.JSONField(default=dict, blank=True)  # the last blocks / card sent (no secrets)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "bridge_cards"
        indexes = [models.Index(fields=["workspace", "proposal"], name="bridge_card_lookup")]


class BridgeOAuthState(models.Model):
    """Single-use Slack install state (hashed, 10 minutes). The callback parks the encrypted result;
    the person who started confirms it while signed in to FloBrain."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    state_hash = models.CharField(max_length=64, unique=True)
    confirm_hash = models.CharField(max_length=64, blank=True, default="")
    result_ciphertext = models.BinaryField(null=True, blank=True)
    key_version = models.PositiveSmallIntegerField(default=1)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "bridge_oauth_states"
