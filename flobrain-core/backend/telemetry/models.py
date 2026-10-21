import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class AppendOnlyMixin:
    def save(self, *args, **kwargs):
        if self._state.adding:
            return super().save(*args, **kwargs)
        raise ValidationError(f"{self.__class__.__name__} rows are append-only")

    def delete(self, *args, **kwargs):
        raise ValidationError(f"{self.__class__.__name__} rows cannot be deleted")


class UsageEvent(AppendOnlyMixin, models.Model):
    OPERATION_CHOICES = [
        ("chat", "Chat"),
        ("transcribe", "Transcribe"),
        ("embed", "Embed"),
        ("tool", "Tool"),
        ("translate", "Translate"),
        ("summarize", "Summarize"),
        ("tts", "TTS"),
        ("render", "Render"),
    ]
    CREDENTIAL_PLATFORM = "platform"
    CREDENTIAL_CUSTOMER = "customer"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="usage_events",
        null=True,
        blank=True,
    )
    user = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="usage_events")
    chat = models.ForeignKey(
        "brain.Chat",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usage_events",
    )
    buddy = models.CharField(max_length=64, blank=True, null=True)
    provider = models.CharField(max_length=64, blank=True, default="")
    model = models.CharField(max_length=128, blank=True, default="")
    operation = models.CharField(max_length=16, choices=OPERATION_CHOICES, default="chat")
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    total_tokens = models.PositiveIntegerField(null=True, blank=True, default=0)
    audio_seconds = models.FloatField(null=True, blank=True)
    credential_source = models.CharField(max_length=16, default=CREDENTIAL_PLATFORM)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=32, default="ok")
    error_code = models.CharField(max_length=64, blank=True, default="")
    estimated = models.BooleanField(default=False)
    team = models.ForeignKey(
        "organizations.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usage_events",
    )
    # Where the call came from (same values as ``AITrace.surface``); empty on rows written before it existed.
    surface = models.CharField(max_length=32, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "usage_events"


class PriceTable(models.Model):
    """Versioned list price per provider and model. Amounts are config, never invented in code.

    ``unit=mtok``: ``input_price``/``output_price`` per million tokens.
    ``unit=gpu_second``: ``input_price`` per GPU render second (provider ``gpu``, model ``render``).
    """

    UNIT_MTOK = "mtok"
    UNIT_GPU_SECOND = "gpu_second"
    UNIT_CHOICES = [(UNIT_MTOK, "Per million tokens"), (UNIT_GPU_SECOND, "Per GPU second")]
    GPU_PROVIDER = "gpu"
    GPU_MODEL = "render"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=64)
    model = models.CharField(max_length=128)
    unit = models.CharField(max_length=16, choices=UNIT_CHOICES, default=UNIT_MTOK)
    input_price = models.DecimalField(max_digits=18, decimal_places=8)
    output_price = models.DecimalField(max_digits=18, decimal_places=8)
    currency = models.CharField(max_length=8, default="USD")
    valid_from = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "price_table"
        ordering = ["-valid_from"]


class Budget(models.Model):
    """A monthly AI budget for the org, one team or one member (spec 6.19, Phase 7).

    Budgets meter platform-credential spend and priced GPU render seconds only; a
    member's own key (BYOK) is never metered and never downgraded (Decision 20).
    ``on_exceed`` says what happens at 100%: ``block`` refuses platform calls,
    ``downgrade`` answers with ``downgrade_model`` where the caller supports it,
    ``alert_only`` lets calls through. Owners and admins get one ``budget_alert``
    per period when spend reaches ``alert_threshold`` (``alerted_period``).
    """

    PERIOD_MONTH = "month"
    PERIOD_CHOICES = [(PERIOD_MONTH, "Month")]
    SCOPE_ORG, SCOPE_TEAM, SCOPE_USER = "org", "team", "user"
    SCOPE_CHOICES = [(SCOPE_ORG, "Organization"), (SCOPE_TEAM, "Team"), (SCOPE_USER, "Member")]
    ON_BLOCK, ON_DOWNGRADE, ON_ALERT = "block", "downgrade", "alert_only"
    ON_EXCEED_CHOICES = [(ON_BLOCK, "Block"), (ON_DOWNGRADE, "Downgrade"), (ON_ALERT, "Alert only")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="ai_budgets")
    scope_type = models.CharField(max_length=8, choices=SCOPE_CHOICES, default=SCOPE_ORG)
    scope_id = models.UUIDField(null=True, blank=True)  # team or user id; empty for the org budget
    period = models.CharField(max_length=16, choices=PERIOD_CHOICES, default=PERIOD_MONTH)
    cap_amount = models.DecimalField(max_digits=18, decimal_places=4)
    currency = models.CharField(max_length=8, default="USD")
    on_exceed = models.CharField(max_length=12, choices=ON_EXCEED_CHOICES, default=ON_BLOCK)
    downgrade_model = models.CharField(max_length=128, blank=True, default="")
    alert_threshold = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.80"))
    alerted_period = models.CharField(max_length=7, blank=True, default="")  # "YYYY-MM" of the last alert
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_budgets"
        constraints = [
            models.UniqueConstraint(
                fields=["org", "period"], condition=models.Q(scope_type="org"), name="unique_org_budget_period"
            ),
            models.UniqueConstraint(
                fields=["org", "scope_type", "scope_id", "period"],
                condition=~models.Q(scope_type="org"),
                name="unique_scoped_budget_period",
            ),
        ]


class AITrace(AppendOnlyMixin, models.Model):
    SURFACE_CHOICES = [
        ("room_ai", "Room AI"),
        ("buddy", "Buddy"),
        ("v1_chat", "V1 chat"),
        ("knowledge_ask", "Knowledge ask"),
        ("content_studio", "Content studio"),
        ("translation", "Translation"),
        ("meeting", "Meeting"),
        ("mcp", "MCP"),
        ("public_api", "Public API"),
        ("scheduled_agent", "Scheduled agent"),
        ("external_agent", "External agent"),
        ("meeting_bot", "Meeting bot"),
        ("evaluation", "Evaluation"),
        ("learning", "Learning"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="ai_traces",
        null=True,
        blank=True,
    )
    user = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="ai_traces")
    request_id = models.CharField(max_length=64, db_index=True)
    surface = models.CharField(max_length=32, choices=SURFACE_CHOICES, default="v1_chat")
    room = models.CharField(max_length=64, blank=True, null=True)
    buddy = models.CharField(max_length=64, blank=True, null=True)
    model = models.CharField(max_length=128, blank=True, default="")
    context_sources = models.JSONField(default=list, blank=True)
    tool_calls = models.JSONField(default=list, blank=True)
    permission_decisions = models.JSONField(default=list, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=16, default="completed")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "ai_traces"


class ProductEvent(AppendOnlyMixin, models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="product_events")
    user = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="product_events")
    name = models.CharField(max_length=80, db_index=True)
    properties = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "product_events"


class FeedbackItem(models.Model):
    KIND_CHOICES = [("bug", "Bug"), ("idea", "Idea"), ("question", "Question")]
    STATUS_NEW = "new"
    STATUS_CHOICES = [
        (STATUS_NEW, "New"),
        ("triaged", "Triaged"),
        ("closed", "Closed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="feedback_items")
    user = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="feedback_items")
    page = models.CharField(max_length=255)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    text = models.TextField()
    screenshot_file = models.CharField(max_length=500, blank=True, default="")
    # What the screen showed, in the reporter's words, only when they chose to include it.
    screenshot_note = models.TextField(blank=True, default="")
    browser = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_NEW)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "feedback_items"
