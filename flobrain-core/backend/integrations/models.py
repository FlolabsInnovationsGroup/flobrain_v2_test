import uuid

from django.db import models
from django.utils import timezone

DEFAULT_TOOLS = (
    ("Figma", "https://www.figma.com"),
    ("Canva", "https://www.canva.com"),
    ("Cursor", "https://cursor.com"),
    ("Notion", "https://www.notion.so"),
    ("Discord", "https://discord.com"),
    ("GitHub", "https://github.com"),
)


class ExternalTool(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="external_tools")
    name = models.CharField(max_length=80)
    url = models.URLField()
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "external_tools"
        ordering = ["sort_order", "name"]


class AICredential(models.Model):
    """A customer LLM key (BYOK, Decisions 20 and 30, E20).

    ``owner`` empty means an org key (owner/admin manage it). ``owner`` set means a
    personal key that only that user can see or use. The secret is stored only as
    AES-256-GCM ciphertext and is never returned; ``last4`` is for display.
    """

    SCOPE_ORG = "org"
    SCOPE_PERSONAL = "personal"

    STATUS_PENDING = "pending"
    STATUS_ACTIVE = "active"
    STATUS_REJECTED = "rejected"
    STATUS_INDETERMINATE = "indeterminate"
    STATUS_DISABLED = "disabled"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_INDETERMINATE, "Indeterminate"),
        (STATUS_DISABLED, "Disabled"),
        (STATUS_EXPIRED, "Expired"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="ai_credentials")
    owner = models.ForeignKey(
        "users.User", on_delete=models.CASCADE, null=True, blank=True, related_name="ai_credentials"
    )
    provider = models.CharField(max_length=40, default="openai_compatible")
    base_url = models.CharField(max_length=255)
    label = models.CharField(max_length=80, blank=True, default="")
    ciphertext = models.BinaryField()
    key_version = models.PositiveSmallIntegerField(default=1)
    last4 = models.CharField(max_length=4)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    last_error = models.CharField(max_length=40, blank=True, default="")
    last_checked_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, related_name="ai_credentials_created"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_credentials"
        indexes = [models.Index(fields=["org", "owner", "status"], name="ai_credential_scope")]

    @property
    def scope(self) -> str:
        return self.SCOPE_PERSONAL if self.owner_id else self.SCOPE_ORG

    def api_key(self) -> str:
        from integrations.crypto import decrypt

        return decrypt(self.ciphertext, self.id, self.org_id, self.key_version)

    def __repr__(self):  # never print the ciphertext or the secret
        return f"<AICredential {self.id} {self.scope} {self.status} ****{self.last4}>"

    __str__ = __repr__


# Write-back connectors (growth round W4) live in their own module.
from integrations.write.models import WriteActionToggle, WriteConnection, WriteOAuthState  # noqa: E402,F401
