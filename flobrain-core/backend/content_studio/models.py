import uuid

from django.db import models
from django.utils import timezone


class BrandKit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="brand_kits")
    name = models.CharField(max_length=80)
    logos = models.JSONField(default=list, blank=True)  # asset ids
    fonts = models.JSONField(default=dict, blank=True)
    colors = models.JSONField(default=dict, blank=True)
    intro_asset = models.ForeignKey("MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    outro_asset = models.ForeignKey("MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    caption_style = models.JSONField(default=dict, blank=True)
    watermark = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "content_brand_kits"


class ContentTemplate(models.Model):
    KINDS = ("question_card", "quote", "clip_frame", "lower_third", "custom")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="content_templates")
    slug = models.SlugField(max_length=80)
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=16, default="custom")
    spec = models.JSONField(default=dict)
    is_builtin = models.BooleanField(default=False)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "content_templates"
        constraints = [models.UniqueConstraint(fields=["org", "slug"], name="unique_content_template")]


class MediaAsset(models.Model):
    KIND_VIDEO, KIND_AUDIO, KIND_IMAGE = "video", "audio", "image"
    STATUS_PENDING, STATUS_READY = "pending", "ready"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="media_assets")
    uploaded_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="media_assets")
    kind = models.CharField(max_length=8)
    name = models.CharField(max_length=200)
    content_type = models.CharField(max_length=80)
    storage_key = models.CharField(max_length=300)
    size_bytes = models.BigIntegerField(default=0)
    status = models.CharField(max_length=8, default=STATUS_PENDING)
    duration_seconds = models.FloatField(null=True, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    # Word timings: [{"w": "hello", "start": 0.12, "end": 0.40, "speaker": "S1"}]
    transcript_words = models.JSONField(default=list, blank=True)
    # "" (none yet), "running", "done", "failed": state of POST …/assets/{id}/transcribe.
    transcript_status = models.CharField(max_length=8, blank=True, default="")
    # Faces counted by detection (no identification). None = not analysed yet.
    face_count = models.PositiveIntegerField(null=True, blank=True)
    # Storage ETag recorded at /complete. A later overwrite of the object is detected and refused.
    source_etag = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "content_media_assets"


class ContentProject(models.Model):
    STATUS_DRAFT, STATUS_PROCESSING, STATUS_READY, STATUS_FAILED = "draft", "processing", "ready", "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="content_projects")
    owner = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="content_projects")
    title = models.CharField(max_length=200)
    source_assets = models.ManyToManyField(MediaAsset, blank=True, related_name="projects")
    brand_kit = models.ForeignKey(BrandKit, on_delete=models.SET_NULL, null=True, blank=True, related_name="projects")
    template = models.ForeignKey(
        ContentTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name="projects"
    )
    status = models.CharField(max_length=12, default=STATUS_DRAFT)
    target_platforms = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "content_projects"


class RenderJob(models.Model):
    PRESETS = {"9x16_1080": (1080, 1920), "16x9_1080": (1920, 1080), "1x1_1080": (1080, 1080)}
    STATUS_QUEUED, STATUS_RUNNING, STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELLED = (
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="render_jobs")
    project = models.ForeignKey(ContentProject, on_delete=models.CASCADE, related_name="renders")
    requested_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="render_jobs")
    edl_version = models.PositiveIntegerField(null=True, blank=True)
    preset = models.CharField(max_length=16)
    spec = models.JSONField(default=dict)  # frozen at queue time: what the worker renders
    status = models.CharField(max_length=10, default=STATUS_QUEUED, db_index=True)
    worker = models.ForeignKey("workers.WorkerToken", on_delete=models.SET_NULL, null=True, blank=True, related_name="jobs")
    progress = models.PositiveSmallIntegerField(default=0)
    gpu_seconds = models.FloatField(default=0)
    output_key = models.CharField(max_length=300, blank=True, default="")
    output_meta = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=200, blank=True, default="")
    queued_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "content_render_jobs"


class EditDecisionList(models.Model):
    """One version of a project's edits (spec 6.16). The source files never change; undo = an earlier version."""

    BY_USER, BY_AI = "user", "ai"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="edls")
    project = models.ForeignKey(ContentProject, on_delete=models.CASCADE, related_name="edls")
    version = models.PositiveIntegerField()
    operations = models.JSONField(default=list)
    created_by_kind = models.CharField(max_length=4, default=BY_USER)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "content_edls"
        constraints = [models.UniqueConstraint(fields=["project", "version"], name="unique_edl_version")]


class ClipSuggestion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="clip_suggestions")
    project = models.ForeignKey(ContentProject, on_delete=models.CASCADE, related_name="clip_suggestions")
    asset = models.ForeignKey(MediaAsset, on_delete=models.CASCADE, related_name="clip_suggestions")
    start = models.FloatField()
    end = models.FloatField()
    hook_text = models.CharField(max_length=200)
    score = models.FloatField(default=0)
    reason = models.CharField(max_length=300, blank=True, default="")
    accepted = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "content_clip_suggestions"
        ordering = ["-score"]


# --- consent, social accounts, publishing (9d) ----------------------------------

SCOPES = ("internal", "public_social", "marketing")  # each scope includes the ones before it


class ConsentRecord(models.Model):
    """A person's consent for media of them (Decision 37). Revocable; revocation blocks pending publishes."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="consents")
    person_user = models.ForeignKey(
        "users.User", on_delete=models.CASCADE, null=True, blank=True, related_name="consents_given"
    )
    person_name = models.CharField(max_length=120, blank=True, default="")
    person_email = models.EmailField(blank=True, default="")
    scope = models.CharField(max_length=16)
    media_asset = models.ForeignKey(
        MediaAsset, on_delete=models.CASCADE, null=True, blank=True, related_name="consents"
    )  # empty = blanket consent for this scope
    granted_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    evidence_key = models.CharField(max_length=300, blank=True, default="")
    recorded_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        db_table = "content_consents"


class AssetPerson(models.Model):
    """A person tagged as appearing in an asset. Detection may count faces; it never identifies anyone."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset = models.ForeignKey(MediaAsset, on_delete=models.CASCADE, related_name="people")
    person_user = models.ForeignKey("users.User", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    person_name = models.CharField(max_length=120, blank=True, default="")
    person_email = models.EmailField(blank=True, default="")
    tagged_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        db_table = "content_asset_people"


class SocialAccount(models.Model):
    STATUS_CONNECTED, STATUS_EXPIRED, STATUS_REVOKED = "connected", "expired", "revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="social_accounts")
    platform = models.CharField(max_length=16)
    display_name = models.CharField(max_length=120)
    external_account_id = models.CharField(max_length=120, blank=True, default="")
    token_ciphertext = models.BinaryField()  # AES-GCM (integrations.crypto), bound to this row and org
    key_version = models.PositiveSmallIntegerField(default=1)
    scopes = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, default=STATUS_CONNECTED)
    private_only = models.BooleanField(default=False)  # unaudited apps post privately (Q16)
    connected_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "content_social_accounts"

    def tokens(self) -> dict:
        import json

        from integrations.crypto import decrypt

        return json.loads(decrypt(self.token_ciphertext, self.id, self.org_id, self.key_version))

    def __repr__(self):
        return f"<SocialAccount {self.platform} {self.display_name} {self.status}>"

    __str__ = __repr__


class OAuthState(models.Model):
    """Single-use, 10-minute OAuth state with the PKCE verifier kept server-side (spec 7)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    platform = models.CharField(max_length=16)
    state_hash = models.CharField(max_length=64, unique=True)
    verifier_ciphertext = models.BinaryField()
    key_version = models.PositiveSmallIntegerField(default=1)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    # After the provider callback: tokens wait here until the same signed-in user confirms
    # with the one-time code that only the browser finishing the flow received.
    confirm_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    result_ciphertext = models.BinaryField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "content_oauth_states"


class PublishJob(models.Model):
    AWAITING, APPROVED, SCHEDULED, PUBLISHING, PUBLISHED, FAILED, CANCELLED = (
        "awaiting_approval",
        "approved",
        "scheduled",
        "publishing",
        "published",
        "failed",
        "cancelled",
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="publish_jobs")
    project = models.ForeignKey(ContentProject, on_delete=models.CASCADE, related_name="publish_jobs")
    render = models.ForeignKey(RenderJob, on_delete=models.CASCADE, related_name="publish_jobs")
    social_account = models.ForeignKey(SocialAccount, on_delete=models.CASCADE, related_name="publish_jobs")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    hashtags = models.JSONField(default=list, blank=True)
    thumbnail_key = models.CharField(max_length=300, blank=True, default="")
    scheduled_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, default=AWAITING, db_index=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    approved_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_hash = models.CharField(max_length=64, blank=True, default="")
    external_post_id = models.CharField(max_length=200, blank=True, default="")
    external_url = models.URLField(blank=True, default="")
    visibility = models.CharField(max_length=8, blank=True, default="")  # public | private (as posted)
    metrics = models.JSONField(default=dict, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "content_publish_jobs"
