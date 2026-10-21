import uuid

from django.db import models
from django.utils import timezone


class Plan(models.Model):
    """A plan. ``entitlements`` = {"flags": [...], "limits": {"seats": int, "renders_per_month": int}}.
    Written only by platform admins or the verified Stripe webhook."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    price_cents = models.PositiveIntegerField(default=0)  # per seat per interval; numbers are config (Q22)
    currency = models.CharField(max_length=3, default="USD")
    interval = models.CharField(max_length=8, default="month")
    entitlements = models.JSONField(default=dict)
    stripe_price_id = models.CharField(max_length=80, blank=True, default="")
    is_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    # Workspace pricing (M8, flag ``workspace_pricing``). Prices stay config: these rows (or
    # billing_v2/sample_plans.py for seeding) are the only place a price lives on the server.
    UNIT_PER_SEAT = "per_seat"
    UNIT_PER_WORKSPACE = "per_workspace"
    UNITS = ((UNIT_PER_SEAT, "Per person"), (UNIT_PER_WORKSPACE, "Per workspace"))
    OVERAGE_BLOCK = "block"
    OVERAGE_PROMPT = "prompt_upgrade"
    OVERAGE = ((OVERAGE_BLOCK, "Block new people"), (OVERAGE_PROMPT, "Block and suggest an upgrade"))

    billing_unit = models.CharField(max_length=16, choices=UNITS, default=UNIT_PER_SEAT)
    included_seats = models.PositiveIntegerField(null=True, blank=True)  # workspace plans: people included for one price
    overage_policy = models.CharField(max_length=16, choices=OVERAGE, default=OVERAGE_BLOCK)  # never a silent charge
    ai_allowance_per_workspace = models.PositiveIntegerField(null=True, blank=True)  # buddy answers per month, whole workspace
    price_yearly_cents = models.PositiveIntegerField(default=0)  # per seat (or per workspace) per year; 0 = 12 x monthly
    tier = models.SlugField(max_length=40, blank=True, default="")  # pairs a per-seat and a workspace plan with the same features

    class Meta:
        db_table = "billing_plans"

    @property
    def per_workspace(self) -> bool:
        return self.billing_unit == self.UNIT_PER_WORKSPACE

    def flags(self) -> set[str]:
        return set((self.entitlements or {}).get("flags") or [])

    def limit(self, name):
        value = ((self.entitlements or {}).get("limits") or {}).get(name)
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


class Subscription(models.Model):
    ACTIVE_STATES = ("trialing", "active", "past_due")  # past_due keeps access during the grace period

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.OneToOneField("organizations.Organization", on_delete=models.CASCADE, related_name="subscription")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=12, default="trialing")
    seats = models.PositiveIntegerField(default=1)
    stripe_customer_id = models.CharField(max_length=80, blank=True, default="")
    stripe_subscription_id = models.CharField(max_length=80, blank=True, default="", db_index=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    interval = models.CharField(max_length=8, default="month")  # month | year (M8)
    last_event_at = models.DateTimeField(null=True, blank=True)  # Stripe event.created of the last applied change
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "billing_subscriptions"


class UsageInvoiceLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="invoice_lines")
    subscription = models.ForeignKey(Subscription, on_delete=models.SET_NULL, null=True, related_name="lines")
    period = models.CharField(max_length=7)  # YYYY-MM
    metric = models.CharField(max_length=40)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    unit_price = models.DecimalField(max_digits=18, decimal_places=6)
    amount = models.DecimalField(max_digits=18, decimal_places=4)

    class Meta:
        db_table = "billing_usage_lines"
        constraints = [models.UniqueConstraint(fields=["org", "period", "metric"], name="unique_usage_line")]


class StripeEvent(models.Model):
    """Processed webhook ids, so a retried delivery is applied once."""

    event_id = models.CharField(max_length=80, primary_key=True)
    type = models.CharField(max_length=80)
    received_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "billing_stripe_events"


class Invoice(models.Model):
    """A copy of a Stripe invoice (written only by the verified webhook, or the demo seed), so the
    billing page can list invoices without calling Stripe on every view. The PDF lives at Stripe."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="billing_invoices")
    stripe_invoice_id = models.CharField(max_length=80, blank=True, default="", db_index=True)
    number = models.CharField(max_length=40, blank=True, default="")
    status = models.CharField(max_length=16, default="paid")  # draft | open | paid | void | uncollectible
    amount_cents = models.IntegerField(default=0)
    currency = models.CharField(max_length=3, default="USD")
    plan_code = models.CharField(max_length=40, blank=True, default="")
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    hosted_url = models.URLField(max_length=500, blank=True, default="")  # https://invoice.stripe.com/... only
    demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "billing_invoices"
        ordering = ["-created_at"]
