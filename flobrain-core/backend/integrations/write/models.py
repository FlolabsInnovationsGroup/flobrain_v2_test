"""Models for write-back connectors. Imported from ``integrations.models`` so they belong to the
``integrations`` app. Secrets are AES-256-GCM ciphertext bound to the row id and org id; they are
never serialized."""

import uuid

from django.db import models
from django.utils import timezone


class WriteConnection(models.Model):
    """One account FloBrain may write to. ``owner`` empty: shared by the org (admins connect it).
    ``owner`` set: a personal Google or Microsoft account only that person's approved actions use."""

    STATUS_NOT_SET_UP = "not_set_up"
    STATUS_CONNECTED = "connected"
    STATUS_EXPIRED = "expired"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_NOT_SET_UP, "Not set up"),
        (STATUS_CONNECTED, "Connected"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_ERROR, "Error"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="write_connections")
    owner = models.ForeignKey(
        "users.User", on_delete=models.CASCADE, null=True, blank=True, related_name="write_connections"
    )
    provider = models.CharField(max_length=32)
    account_label = models.CharField(max_length=160, blank=True, default="")
    scopes = models.JSONField(default=list, blank=True)
    # Non-secret facts the executors need: Jira cloud id and site, HubSpot portal, Zoho data center, Odoo URL.
    config = models.JSONField(default=dict, blank=True)
    access_ciphertext = models.BinaryField(null=True, blank=True)
    refresh_ciphertext = models.BinaryField(null=True, blank=True)
    key_version = models.PositiveSmallIntegerField(default=1)
    secret_hint = models.CharField(max_length=4, blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_CONNECTED)
    last_error = models.CharField(max_length=120, blank=True, default="")
    # Demo mode only: a simulated connection that never reaches the network.
    demo = models.BooleanField(default=False)
    connected_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "write_connections"
        constraints = [
            models.UniqueConstraint(
                fields=["org", "provider"], condition=models.Q(owner__isnull=True), name="unique_org_write_connection"
            ),
            models.UniqueConstraint(
                fields=["org", "provider", "owner"],
                condition=models.Q(owner__isnull=False),
                name="unique_personal_write_connection",
            ),
        ]

    @property
    def scope(self) -> str:
        return "personal" if self.owner_id else "org"

    def _aad(self, part: str) -> str:
        return f"write:{self.id}:{part}"

    def set_secrets(self, access: str, refresh: str | None = None, keep_refresh: bool = False) -> None:
        from integrations import crypto

        self.access_ciphertext = crypto.encrypt(access, self._aad("access"), self.org_id)
        if refresh:
            self.refresh_ciphertext = crypto.encrypt(refresh, self._aad("refresh"), self.org_id)
        elif not keep_refresh:
            self.refresh_ciphertext = None
        self.key_version = crypto.current_key_version()

    def access_token(self) -> str:
        from integrations import crypto

        if not self.access_ciphertext:
            raise crypto.CredentialCryptoError("no token stored")
        return crypto.decrypt(self.access_ciphertext, self._aad("access"), self.org_id, self.key_version)

    def refresh_token(self) -> str:
        from integrations import crypto

        if not self.refresh_ciphertext:
            return ""
        return crypto.decrypt(self.refresh_ciphertext, self._aad("refresh"), self.org_id, self.key_version)

    def wipe(self) -> None:
        self.access_ciphertext = None
        self.refresh_ciphertext = None
        self.secret_hint = ""

    def __repr__(self):  # never the tokens
        return f"<WriteConnection {self.provider} {self.scope} {self.status}>"

    __str__ = __repr__


class WriteOAuthState(models.Model):
    """Single-use, 10-minute OAuth state with the PKCE verifier kept server-side. After the provider
    callback the tokens wait here, encrypted, until the person who started the flow confirms with a
    one-time code only their browser received (so a forwarded link can't attach someone's account)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    provider = models.CharField(max_length=32)
    personal = models.BooleanField(default=False)
    state_hash = models.CharField(max_length=64, unique=True)
    verifier_ciphertext = models.BinaryField()
    key_version = models.PositiveSmallIntegerField(default=1)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    confirm_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    result_ciphertext = models.BinaryField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "write_oauth_states"


class WriteActionToggle(models.Model):
    """An admin's switch for one write action in one org. No row means the action is on."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    tool_key = models.CharField(max_length=64)
    enabled = models.BooleanField(default=True)
    updated_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "write_action_toggles"
        constraints = [models.UniqueConstraint(fields=["org", "tool_key"], name="unique_write_action_toggle")]
