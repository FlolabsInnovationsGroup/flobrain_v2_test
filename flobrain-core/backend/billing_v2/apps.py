from django.apps import AppConfig


class BillingV2Config(AppConfig):
    """New billing tables (Phase 17b). The old customer_billing/payment_history tables stay untouched (Q37)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "billing_v2"
    label = "billing_v2"
    verbose_name = "Billing (V2)"
