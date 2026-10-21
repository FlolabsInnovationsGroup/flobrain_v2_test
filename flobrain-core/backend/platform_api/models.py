import hashlib
import secrets
import uuid

from django.db import models
from django.utils import timezone

PAT_PREFIX = "fbp_"
SCOPES = ("tasks:read", "tasks:write", "rooms:read", "rooms:write", "time:read", "knowledge:read", "mcp")


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class PersonalAccessToken(models.Model):
    """Scoped token for the public API and MCP (spec 6.18, Decision 42). Only the hash is stored."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="access_tokens")
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="access_tokens")
    name = models.CharField(max_length=80)
    token_hash = models.CharField(max_length=64, unique=True)
    last4 = models.CharField(max_length=4)
    scopes = models.JSONField(default=list)
    created_at = models.DateTimeField(default=timezone.now)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_access_tokens"

    @classmethod
    def issue(cls, user, org, name, scopes, expires_at=None):
        raw = PAT_PREFIX + secrets.token_urlsafe(32)
        row = cls.objects.create(
            user=user, org=org, name=name[:80], token_hash=hash_token(raw), last4=raw[-4:], scopes=scopes, expires_at=expires_at
        )
        return row, raw

    def __repr__(self):
        return f"<PersonalAccessToken {self.name} ****{self.last4}>"

    __str__ = __repr__


class WebhookEndpoint(models.Model):
    EVENTS = ("task.created", "task.completed", "member.joined", "meeting.ended", "content.published")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="webhooks")
    url = models.URLField(max_length=500)
    events = models.JSONField(default=list)
    secret_ciphertext = models.BinaryField()
    key_version = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "webhook_endpoints"

    def secret(self) -> str:
        from integrations.crypto import decrypt

        return decrypt(self.secret_ciphertext, self.id, self.org_id, self.key_version)


class WebhookDelivery(models.Model):
    PENDING, DELIVERED, FAILED = "pending", "delivered", "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    endpoint = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries")
    event = models.CharField(max_length=40)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=10, default=PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    response_code = models.PositiveSmallIntegerField(null=True, blank=True)
    error = models.CharField(max_length=200, blank=True, default="")
    next_attempt_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(default=timezone.now)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "webhook_deliveries"
        ordering = ["-created_at"]


class ExternalAgentServer(models.Model):
    """An external MCP server an admin connected for buddies (Decision 48, spec 6.19).

    Its host must be on the org allowlist (owner) and on ``EXTERNAL_AGENT_ALLOWED_HOSTS`` (the
    installation's upper bound). ``tools_cache`` is the imported ``tools/list``; it is usable only
    while ``tools_hash == tools_approved_hash`` (the owner approved exactly this list).
    """

    STATUS_PENDING, STATUS_CONNECTED, STATUS_ERROR = "pending", "connected", "error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="external_agents")
    name = models.CharField(max_length=80)
    url = models.URLField(max_length=500)
    transport = models.CharField(max_length=16, default="http")
    allowed = models.BooleanField(default=False)
    tools_cache = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, default=STATUS_PENDING)
    last_error = models.CharField(max_length=200, blank=True, default="")
    last_checked_at = models.DateTimeField(null=True, blank=True)
    server_info = models.JSONField(default=dict, blank=True)
    tools_hash = models.CharField(max_length=64, blank=True, default="")
    tools_approved_hash = models.CharField(max_length=64, blank=True, default="")
    tools_approved_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    token_ciphertext = models.BinaryField(null=True, blank=True)  # optional bearer token for the server, encrypted
    key_version = models.PositiveSmallIntegerField(default=1)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "external_agent_servers"

    @property
    def tools_approved(self) -> bool:
        return bool(self.tools_hash) and self.tools_hash == self.tools_approved_hash

    def token(self) -> str:
        if not self.token_ciphertext:
            return ""
        from integrations.crypto import decrypt

        return decrypt(bytes(self.token_ciphertext), self.id, self.org_id, self.key_version)


class ExternalAgentHost(models.Model):
    """The owner's allowlist of external agent hosts (Decision 48). The env list is the upper bound."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="external_agent_hosts")
    host = models.CharField(max_length=253)
    note = models.CharField(max_length=200, blank=True, default="")
    added_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "external_agent_hosts"
        constraints = [models.UniqueConstraint(fields=["org", "host"], name="unique_external_agent_host")]


class ExternalAgentCall(models.Model):
    """One call to an external agent tool. A buddy's call waits for its person's approval; the
    output is stored as untrusted, quoted data and is never read as instructions."""

    PROPOSED, EXECUTED, FAILED, REJECTED, EXPIRED = "proposed", "executed", "failed", "rejected", "expired"
    VIA_TEST, VIA_BUDDY = "test", "buddy"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="external_agent_calls")
    server = models.ForeignKey(ExternalAgentServer, on_delete=models.CASCADE, related_name="calls")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    buddy = models.ForeignKey("buddies.Buddy", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    chat = models.ForeignKey("brain.Chat", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    via = models.CharField(max_length=8, default=VIA_BUDDY)
    tool = models.CharField(max_length=128)
    arguments = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, default=PROPOSED, db_index=True)
    output = models.TextField(blank=True, default="")  # untrusted text, size-capped
    is_error = models.BooleanField(default=False)
    flags = models.JSONField(default=list, blank=True)  # e.g. ["instructions_ignored", "redacted"]
    error = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "external_agent_calls"
        ordering = ["-created_at"]


class DemoInboxDelivery(models.Model):
    """What the built-in demo receiver got (DEMO_MODE only): the body as sent and whether the
    signature checked out with the endpoint's secret, like a real receiver would check it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    endpoint = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name="+")
    event = models.CharField(max_length=40)
    body = models.TextField()
    signature = models.CharField(max_length=200, blank=True, default="")
    signature_valid = models.BooleanField(default=False)
    received_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "demo_inbox_deliveries"
        ordering = ["-received_at"]


class StatusSubscription(models.Model):
    """Email updates from the public status page. Confirmed by a link (only its hash is stored);
    unsubscribe links are signed with the server secret."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    confirm_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    confirm_sent_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "status_subscriptions"


class Incident(models.Model):
    SEVERITIES = ("minor", "major", "critical")
    STATUSES = ("investigating", "identified", "monitoring", "resolved")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, null=True, blank=True, related_name="incidents"
    )  # empty = platform-wide (is_platform_admin only)
    title = models.CharField(max_length=200)
    severity = models.CharField(max_length=10, default="minor")
    status = models.CharField(max_length=14, default="investigating")
    components = models.JSONField(default=list, blank=True)
    impact = models.TextField(blank=True, default="")
    user_action = models.TextField(blank=True, default="")
    is_public = models.BooleanField(default=False)
    updates = models.JSONField(default=list, blank=True)  # [{"at", "status", "message"}]
    mitigation = models.TextField(blank=True, default="")
    next_update_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "incidents"
        ordering = ["-created_at"]
