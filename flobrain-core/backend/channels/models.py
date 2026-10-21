"""Channels (W2): WhatsApp, Telegram and the website chat; links between people and their phones; the
customer buddy's conversations.

Secrets (WhatsApp access token, app secret, verify token; Telegram bot token, secret token) are kept
only as AES-256-GCM ciphertext bound to the connection and org (``integrations.crypto``). Responses
carry masked hints (last 4 characters) and never the secret.
"""

import uuid

from django.db import models
from django.utils import timezone


class ChannelConnection(models.Model):
    WHATSAPP, TELEGRAM, WEBSITE = "whatsapp", "telegram", "website"
    KIND_CHOICES = [(WHATSAPP, "WhatsApp"), (TELEGRAM, "Telegram"), (WEBSITE, "Website chat")]

    NOT_SET_UP, ACTIVE, ERROR = "not_set_up", "active", "error"
    STATUS_CHOICES = [(NOT_SET_UP, "Not set up"), (ACTIVE, "Active"), (ERROR, "Error")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="channel_connections")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    label = models.CharField(max_length=120, blank=True, default="")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=NOT_SET_UP)
    # Non-secret settings: WhatsApp phone_number_id / waba_id / display_phone; Telegram bot_username;
    # website allowed_origins.
    config = models.JSONField(default=dict, blank=True)
    secrets_ciphertext = models.BinaryField(null=True, blank=True)
    key_version = models.PositiveSmallIntegerField(default=1)
    secret_hints = models.JSONField(default=dict, blank=True)  # {"access_token": "…abcd"}
    site_key = models.CharField(max_length=40, unique=True, null=True, blank=True)
    serve_team = models.BooleanField(default=True)  # people talk to their buddies here
    serve_customers = models.BooleanField(default=False)  # customers talk to the customer buddy here
    # The buddy employees reach from this channel (empty: the first built-in buddy they can see).
    team_buddy = models.ForeignKey("buddies.Buddy", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    demo = models.BooleanField(default=False)
    last_error = models.CharField(max_length=200, blank=True, default="")
    last_checked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "channel_connections"
        indexes = [models.Index(fields=["org", "kind"], name="channel_conn_org_kind")]

    def __repr__(self):  # never the ciphertext
        return f"<ChannelConnection {self.kind} {self.id}>"


class ChannelLink(models.Model):
    """A FloBrain person linked to a WhatsApp number or Telegram chat on one connection.

    ``pending`` rows carry a hashed 6-digit code the person sends to the bot; ``active`` rows carry the
    sender id. A code is single use and expires; wrong guesses are counted and limited.
    """

    PENDING, ACTIVE, REVOKED, EXPIRED = "pending", "active", "revoked", "expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="channel_links")
    connection = models.ForeignKey(ChannelConnection, on_delete=models.CASCADE, related_name="links")
    status = models.CharField(max_length=10, default=PENDING)
    code_hash = models.CharField(max_length=64, blank=True, default="")
    code_expires_at = models.DateTimeField(null=True, blank=True)
    external_id = models.CharField(max_length=64, blank=True, default="")  # phone (wa_id) or Telegram chat id
    external_name = models.CharField(max_length=120, blank=True, default="")
    chat = models.ForeignKey("brain.Chat", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    linked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "channel_links"
        indexes = [models.Index(fields=["connection", "status", "external_id"], name="channel_link_lookup")]


class InboundEvent(models.Model):
    """One provider message, kept once (idempotency on the provider's message id)."""

    RECEIVED, DONE, IGNORED, FAILED = "received", "done", "ignored", "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    connection = models.ForeignKey(ChannelConnection, on_delete=models.CASCADE, related_name="events")
    provider_message_id = models.CharField(max_length=128)
    sender = models.CharField(max_length=64, blank=True, default="")
    sender_name = models.CharField(max_length=120, blank=True, default="")
    text = models.TextField(blank=True, default="")
    media = models.JSONField(default=dict, blank=True)  # {"type": "voice", "ref": "<provider media id>"}
    status = models.CharField(max_length=10, default=RECEIVED)
    outcome = models.CharField(max_length=40, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "channel_inbound_events"
        constraints = [models.UniqueConstraint(fields=["connection", "provider_message_id"], name="unique_channel_inbound")]


class CustomerSettings(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.OneToOneField("organizations.Organization", on_delete=models.CASCADE, related_name="customer_settings")
    auto_reply = models.BooleanField(default=False)  # off: AI answers wait as drafts for a person
    escalation_room = models.ForeignKey("rooms.Room", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    blocked_topics = models.JSONField(default=list, blank=True)
    buddy_name = models.CharField(max_length=60, blank=True, default="")
    greeting = models.CharField(max_length=300, blank=True, default="")
    updated_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "channel_customer_settings"


class CustomerKnowledge(models.Model):
    """A document an admin chose as public for customers. The customer buddy reads only these."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    document = models.ForeignKey("docs.Document", on_delete=models.CASCADE, related_name="+")
    added_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "channel_customer_knowledge"
        constraints = [models.UniqueConstraint(fields=["org", "document"], name="unique_customer_knowledge")]


class CustomerConversation(models.Model):
    OPEN, WAITING_HUMAN, RESOLVED = "open", "waiting_human", "resolved"
    STATUS_CHOICES = [(OPEN, "Open"), (WAITING_HUMAN, "Waiting for a person"), (RESOLVED, "Resolved")]
    MODE_BUDDY, MODE_HUMAN = "buddy", "human"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="customer_conversations")
    connection = models.ForeignKey(ChannelConnection, on_delete=models.CASCADE, related_name="conversations")
    channel = models.CharField(max_length=10, choices=ChannelConnection.KIND_CHOICES)
    external_id = models.CharField(max_length=64, blank=True, default="")  # phone or chat id; empty for the website
    token_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)  # website conversation token
    customer_name = models.CharField(max_length=80, blank=True, default="")
    contact_masked = models.CharField(max_length=40, blank=True, default="")
    status = models.CharField(max_length=14, choices=STATUS_CHOICES, default=OPEN)
    mode = models.CharField(max_length=6, default=MODE_BUDDY)
    escalation_reason = models.CharField(max_length=40, blank=True, default="")
    assigned_room = models.ForeignKey("rooms.Room", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    assignee = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    demo = models.BooleanField(default=False)
    last_customer_at = models.DateTimeField(null=True, blank=True)
    last_message_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "channel_customer_conversations"
        indexes = [
            models.Index(fields=["org", "status", "last_message_at"], name="customer_conv_inbox"),
            models.Index(fields=["connection", "external_id"], name="customer_conv_sender"),
        ]

    @property
    def title(self) -> str:
        """Shown by other apps (the automations ``customer_conversation`` trigger reads ``title``)."""
        return f"{self.customer_name or 'Customer'} ({self.get_channel_display()})"


class CustomerMessage(models.Model):
    CUSTOMER, BUDDY, STAFF, SYSTEM = "customer", "buddy", "staff", "system"
    SENT, DRAFT, REJECTED, FAILED = "sent", "draft", "rejected", "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(CustomerConversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=8)
    text = models.TextField(blank=True, default="")
    status = models.CharField(max_length=8, default=SENT)
    citations = models.JSONField(default=list, blank=True)
    media = models.JSONField(default=dict, blank=True)
    author = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    approved_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    delivery_error = models.CharField(max_length=60, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "channel_customer_messages"
        ordering = ["created_at"]
