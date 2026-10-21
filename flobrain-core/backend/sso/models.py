import uuid

from django.db import models
from django.utils import timezone


class SSOConnection(models.Model):
    """SSO sign-in for one org: OIDC (Phase 17c) or SAML 2.0 (``protocol``), never both at once."""

    PROTOCOL_OIDC = "oidc"
    PROTOCOL_SAML = "saml"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.OneToOneField("organizations.Organization", on_delete=models.CASCADE, related_name="sso")
    protocol = models.CharField(max_length=8, default=PROTOCOL_OIDC)
    issuer = models.URLField(max_length=300)
    client_id = models.CharField(max_length=200)
    secret_ciphertext = models.BinaryField()
    key_version = models.PositiveSmallIntegerField(default=1)
    metadata = models.JSONField(default=dict, blank=True)  # discovery doc subset: endpoints, jwks_uri
    verified_domains = models.JSONField(default=list, blank=True)
    pending_domains = models.JSONField(default=dict, blank=True)  # {domain: token}
    enforced = models.BooleanField(default=False)  # password sign-in off for these domains (owner keeps break-glass)
    enabled = models.BooleanField(default=False)
    # SAML 2.0 (protocol "saml"): the IdP's identity and signing certificate (public, so stored as PEM).
    idp_entity_id = models.CharField(max_length=300, blank=True, default="")
    idp_sso_url = models.URLField(max_length=500, blank=True, default="")
    idp_cert_pem = models.TextField(blank=True, default="")
    idp_cert_fingerprint = models.CharField(max_length=95, blank=True, default="")  # SHA-256, colon hex
    email_attribute = models.CharField(max_length=200, blank=True, default="")  # "" = NameID emailAddress, else `email`
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sso_connections"

    def client_secret(self) -> str:
        from integrations.crypto import decrypt

        return decrypt(self.secret_ciphertext, self.id, self.org_id, self.key_version)


class SSOState(models.Model):
    """Single-use, 10-minute login state: hash of state, nonce, PKCE verifier (encrypted)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(SSOConnection, on_delete=models.CASCADE, related_name="states")
    state_hash = models.CharField(max_length=64, unique=True)
    nonce = models.CharField(max_length=64)
    client_hash = models.CharField(max_length=64, default="")  # the starting browser's nonce (login CSRF)
    verifier_ciphertext = models.BinaryField()
    key_version = models.PositiveSmallIntegerField(default=1)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sso_states"


class SAMLRequest(models.Model):
    """One AuthnRequest we sent (10 minutes, single use): its ID must come back as ``InResponseTo``."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(SSOConnection, on_delete=models.CASCADE, related_name="saml_requests")
    request_id = models.CharField(max_length=64, unique=True)
    relay_hash = models.CharField(max_length=64)  # sha256 of the opaque RelayState
    client_hash = models.CharField(max_length=64, default="")  # the starting browser's nonce (login CSRF)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sso_saml_requests"


class SSOLoginCode(models.Model):
    """One-time code (2 minutes) the browser exchanges for tokens, so tokens never sit in a URL."""

    code_hash = models.CharField(max_length=64, primary_key=True)
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    client_hash = models.CharField(max_length=64, default="")
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sso_login_codes"


class SCIMToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="scim_tokens")
    token_hash = models.CharField(max_length=64, unique=True)
    last4 = models.CharField(max_length=4)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "scim_tokens"


class SCIMGroupMap(models.Model):
    """An IdP group mapped to a FloBrain team. SCIM never grants owner, admin or lead."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="scim_groups")
    external_id = models.CharField(max_length=200)
    display_name = models.CharField(max_length=200)
    team = models.ForeignKey("organizations.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        db_table = "scim_group_maps"
        constraints = [models.UniqueConstraint(fields=["org", "external_id"], name="unique_scim_group")]
