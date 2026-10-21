import uuid

from django.db import models
from django.utils import timezone


class EvalSuite(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="eval_suites")
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True, default="")
    threshold = models.PositiveSmallIntegerField(default=80)  # pass rate (%) the suite must reach
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "pulse_eval_suites"


class EvalCase(models.Model):
    """One prompt and the checks its answer must pass (all deterministic: no AI judging AI)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    suite = models.ForeignKey(EvalSuite, on_delete=models.CASCADE, related_name="cases")
    name = models.CharField(max_length=120)
    prompt = models.TextField()
    must_contain = models.JSONField(default=list, blank=True)
    must_not_contain = models.JSONField(default=list, blank=True)
    max_latency_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "pulse_eval_cases"


class EvalRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    suite = models.ForeignKey(EvalSuite, on_delete=models.CASCADE, related_name="runs")
    model = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(max_length=10, default="queued")  # queued|running|done|failed
    pass_rate = models.FloatField(null=True, blank=True)
    avg_latency_ms = models.PositiveIntegerField(null=True, blank=True)
    started_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "pulse_eval_runs"


class EvalResult(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(EvalRun, on_delete=models.CASCADE, related_name="results")
    case = models.ForeignKey(EvalCase, on_delete=models.CASCADE, related_name="+")
    output = models.TextField(blank=True, default="")
    passed = models.BooleanField(default=False)
    checks = models.JSONField(default=list)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        db_table = "pulse_eval_results"


class RoutingPolicy(models.Model):
    """Which platform model to use and what to fall back to. Never applies to customer keys (Decision 20);
    an org's ``private_only`` policy always wins (Decision 50)."""

    org = models.OneToOneField("organizations.Organization", on_delete=models.CASCADE, primary_key=True, related_name="routing_policy")
    primary_model = models.CharField(max_length=128, blank=True, default="")
    fallback_models = models.JSONField(default=list, blank=True)
    max_task_cost = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    latency_threshold_ms = models.PositiveIntegerField(null=True, blank=True)
    require_approval_for_writes = models.BooleanField(default=True)
    updated_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "pulse_routing_policies"


class AlertRule(models.Model):
    METRICS = ("error_rate", "p95_latency_ms", "daily_cost")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="alert_rules")
    metric = models.CharField(max_length=20)
    threshold = models.FloatField()
    window_minutes = models.PositiveIntegerField(default=60)
    is_active = models.BooleanField(default=True)
    last_fired_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "pulse_alert_rules"
