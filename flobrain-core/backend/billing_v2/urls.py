from django.urls import path

from billing_v2 import views

urlpatterns = [
    path("orgs/<uuid:org_id>/billing", views.OrgBillingView.as_view(), name="v2-billing"),
    path("orgs/<uuid:org_id>/billing/checkout", views.OrgCheckoutView.as_view(), name="v2-billing-checkout"),
    path("orgs/<uuid:org_id>/billing/portal", views.OrgBillingPortalView.as_view(), name="v2-billing-portal"),
    path("orgs/<uuid:org_id>/billing/demo", views.OrgDemoBillingView.as_view(), name="v2-billing-demo"),
    path("orgs/<uuid:org_id>/billing/switch", views.OrgPlanSwitchView.as_view(), name="v2-billing-switch"),
    path("orgs/<uuid:org_id>/billing/invoices", views.OrgInvoicesView.as_view(), name="v2-billing-invoices"),
    path("pricing/calculator", views.PricingCalculatorView.as_view(), name="v2-pricing-calculator"),
    path("platform/plans", views.PlatformPlanListView.as_view(), name="v2-platform-plans"),
    path("platform/orgs/<uuid:org_id>/subscription", views.PlatformSubscriptionView.as_view(), name="v2-platform-subscription"),
    path("billing/stripe/webhook", views.StripeWebhookView.as_view(), name="v2-stripe-webhook"),
]
