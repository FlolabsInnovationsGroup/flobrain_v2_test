"""Buddy evaluation sets and quality gates (market round M5, flag ``buddy_evals``).

An ``EvalSet`` is a list of test questions (``EvalCase``) for one buddy, with a pass mark.
An ``EvalRun`` is one pass of the set through the buddy in sandbox mode (nothing is executed,
proposed, notified or remembered). ``EvalGateEvent`` records each time the gate allowed, blocked
or was overridden before a marketplace submit, a new version or a buddy save.
"""

import uuid
from decimal import Decimal

from django.db import models
from django.utils import timezone

LANG_ANY, LANG_AR, LANG_EN = "any", "ar", "en"
LANGUAGE_CHOICES = [(LANG_ANY, "Any"), (LANG_AR, "Arabic"), (LANG_EN, "English")]


class EvalPolicy(models.Model):
    """Org-wide settings for evals. ``judge_model`` empty means the org's routing policy decides."""

    org = models.OneToOneField("organizations.Organization", on_delete=models.CASCADE, related_name="eval_policy")
    judge_model = models.CharField(max_length=128, blank=True, default="")
    max_run_tokens = models.PositiveIntegerField(default=60000)
    max_run_cost = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True, default=Decimal("1.0000"))
    concurrency = models.PositiveSmallIntegerField(default=3)
    updated_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "buddy_eval_policies"


class EvalSet(models.Model):
    SCHEDULE_OFF, SCHEDULE_DAILY, SCHEDULE_WEEKLY = "off", "daily", "weekly"
    SCHEDULE_CHOICES = [(SCHEDULE_OFF, "Off"), (SCHEDULE_DAILY, "Daily"), (SCHEDULE_WEEKLY, "Weekly")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="eval_sets")
    buddy = models.ForeignKey("buddies.Buddy", on_delete=models.CASCADE, related_name="eval_sets")
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True, default="")
    threshold = models.PositiveSmallIntegerField(default=80)  # pass mark, percent
    max_drop = models.PositiveSmallIntegerField(default=5)  # points below the last accepted run that still pass
    gate_marketplace = models.BooleanField(default=True)
    gate_saves = models.BooleanField(default=False)
    schedule = models.CharField(max_length=8, choices=SCHEDULE_CHOICES, default=SCHEDULE_OFF)
    last_scheduled_at = models.DateTimeField(null=True, blank=True)
    # The run the gate last accepted (passed or overridden): "the previous version" to compare with.
    baseline_run = models.ForeignKey("evals.EvalRun", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "buddy_eval_sets"
        ordering = ["name"]
        indexes = [models.Index(fields=["org", "buddy"], name="eval_set_org_buddy")]


class EvalCase(models.Model):
    """One test question and what a good answer must (not) do. No check means "not checked"."""

    TOOL_ANY = ""  # don't check which tool is proposed
    TOOL_NONE = "none"  # no tool may be proposed

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    eval_set = models.ForeignKey(EvalSet, on_delete=models.CASCADE, related_name="cases")
    position = models.PositiveIntegerField(default=0)
    name = models.CharField(max_length=120, blank=True, default="")
    input = models.TextField()
    context_doc_ids = models.JSONField(default=list, blank=True)
    must_include = models.JSONField(default=list, blank=True)
    must_not_include = models.JSONField(default=list, blank=True)
    must_cite = models.BooleanField(default=False)
    expected_tool = models.CharField(max_length=80, blank=True, default=TOOL_ANY)
    forbidden_tools = models.JSONField(default=list, blank=True)
    max_words = models.PositiveIntegerField(null=True, blank=True)
    language = models.CharField(max_length=4, choices=LANGUAGE_CHOICES, default=LANG_ANY)
    rubric = models.TextField(blank=True, default="")  # empty: no AI judge for this case
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "buddy_eval_cases"
        ordering = ["position", "created_at"]


class EvalRun(models.Model):
    QUEUED, RUNNING, DONE, STOPPED, ERROR = "queued", "running", "done", "stopped", "error"
    STATUS_CHOICES = [(s, s.title()) for s in (QUEUED, RUNNING, DONE, STOPPED, ERROR)]
    MANUAL, SCHEDULE, GATE = "manual", "schedule", "gate"
    TRIGGER_CHOICES = [(MANUAL, "Manual"), (SCHEDULE, "Schedule"), (GATE, "Gate")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="eval_runs")
    eval_set = models.ForeignKey(EvalSet, on_delete=models.CASCADE, related_name="runs")
    buddy = models.ForeignKey("buddies.Buddy", on_delete=models.CASCADE, related_name="eval_runs")
    # sha256 of what decides behaviour: base prompt, buddy prompt, tools, sources mode and model.
    fingerprint = models.CharField(max_length=64, db_index=True)
    version_label = models.CharField(max_length=40, blank=True, default="")
    # The buddy settings this run used (so a queued run tests exactly what was asked). Never returned whole.
    config = models.JSONField(default=dict, blank=True)
    model = models.CharField(max_length=128, blank=True, default="")
    judge_model = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default=QUEUED)
    passed = models.BooleanField(null=True)
    score = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    threshold = models.PositiveSmallIntegerField(default=80)
    cases_total = models.PositiveIntegerField(default=0)
    cases_passed = models.PositiveIntegerField(default=0)
    results = models.JSONField(default=list, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    cost = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("0"))
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    triggered_by = models.CharField(max_length=8, choices=TRIGGER_CHOICES, default=MANUAL)
    gate_context = models.CharField(max_length=16, blank=True, default="")
    user = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    error = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "buddy_eval_runs"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["eval_set", "created_at"], name="eval_run_set_time")]


class EvalGateEvent(models.Model):
    PASSED, BLOCKED, OVERRIDDEN = "passed", "blocked", "overridden"
    OUTCOME_CHOICES = [(PASSED, "Passed"), (BLOCKED, "Blocked"), (OVERRIDDEN, "Overridden")]
    MARKETPLACE, SAVE, CHECK = "marketplace", "save", "check"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    buddy = models.ForeignKey("buddies.Buddy", on_delete=models.CASCADE, related_name="eval_gate_events")
    context = models.CharField(max_length=16, default=MARKETPLACE)
    outcome = models.CharField(max_length=12, choices=OUTCOME_CHOICES)
    # [{set, name, run, score, previous, threshold, max_drop, passed, reason}]
    details = models.JSONField(default=list, blank=True)
    override_reason = models.CharField(max_length=500, blank=True, default="")
    user = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "buddy_eval_gate_events"
        ordering = ["-created_at"]
