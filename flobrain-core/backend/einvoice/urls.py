from django.urls import path

from einvoice import views

P = "orgs/<uuid:org_id>/einvoice"
I = "orgs/<uuid:org_id>/einvoices"

urlpatterns = [
    path(f"{P}/meta", views.MetaView.as_view(), name="v2-einvoice-meta"),
    path(f"{P}/settings/<str:country>", views.SettingsView.as_view(), name="v2-einvoice-settings"),
    path(f"{P}/zatca/csr", views.ZatcaCsrView.as_view(), name="v2-einvoice-zatca-csr"),
    path(f"{P}/zatca/<str:step>", views.ZatcaStepView.as_view(), name="v2-einvoice-zatca-step"),
    path(f"{P}/eta/check", views.EtaCheckView.as_view(), name="v2-einvoice-eta-check"),
    path(f"{P}/residency", views.ResidencyView.as_view(), name="v2-einvoice-residency"),
    path(I, views.InvoiceListView.as_view(), name="v2-einvoices"),
    path(f"{I}/import", views.ImportView.as_view(), name="v2-einvoices-import"),
    path(f"{I}/<uuid:invoice_id>", views.InvoiceDetailView.as_view(), name="v2-einvoice"),
    path(f"{I}/<uuid:invoice_id>/xml", views.XmlView.as_view(), name="v2-einvoice-xml"),
    path(f"{I}/<uuid:invoice_id>/eta-document", views.EtaDocumentView.as_view(), name="v2-einvoice-eta-document"),
    path(f"{I}/<uuid:invoice_id>/signature", views.SignatureView.as_view(), name="v2-einvoice-signature"),
    path(f"{I}/<uuid:invoice_id>/approval/<str:decision>", views.ApprovalView.as_view(), name="v2-einvoice-approval"),
    path(f"{I}/<uuid:invoice_id>/<str:action>", views.InvoiceActionView.as_view(), name="v2-einvoice-action"),
]
