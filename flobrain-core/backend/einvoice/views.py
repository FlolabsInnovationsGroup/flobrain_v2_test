"""E-invoicing API. Every endpoint: active member (403) -> flag ``einvoice`` (501) -> permission (403).

Settings and onboarding (``einvoice.manage``; reading settings needs ``einvoice.view``):
- ``GET  /orgs/{org}/einvoice/meta``                 what the screens need (profiles, chain check)
- ``PUT  /orgs/{org}/einvoice/settings/{SA|EG}``     seller details, environment, EGS fields, ETA
  client id, secret (write-only), signer mode, signer URL and token (write-only)
- ``POST /orgs/{org}/einvoice/zatca/{key|compliance|checks|production|reset}``, ``GET .../zatca/csr``
- ``POST /orgs/{org}/einvoice/eta/check``            ask the ETA for a token with the saved credentials
- ``GET|PATCH /orgs/{org}/einvoice/residency``       data region report; pin a region (owner or admin)
Invoices (``einvoice.view`` to read, ``einvoice.issue`` to change):
- ``GET|POST /orgs/{org}/einvoices``, ``POST /orgs/{org}/einvoices/import`` {provider, ref, country, invoice_type}
- ``GET|PATCH|DELETE /orgs/{org}/einvoices/{id}`` (drafts only change)
- ``POST .../{id}/prepare``  freeze: SA counter, hash chain, signed XML and QR; EG document JSON
- ``POST .../{id}/submit``   create the approval to send (nothing is sent yet)
- ``POST .../{id}/approval/{approve|reject}``  decide your own pending approval
- ``POST .../{id}/poll``     ETA status; ``POST .../{id}/copy`` new draft from this one
- ``GET  .../{id}/xml`` (``?cleared=1``), ``GET .../{id}/eta-document``, ``POST .../{id}/signature``
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from core_v2.views import V2APIView
from einvoice import onboarding, residency, services, sources
from einvoice.models import EG, SA, Invoice
from einvoice.services import EInvoiceError, ISSUE, MANAGE, VIEW
from organizations.models import Organization
from organizations.permissions import IsActiveOrgMember, can, is_org_owner_or_admin
from organizations.services.core import audit

MAX_LIST = 200


def _err(code, details, status=400, **extra):
    return Response({"error": code, "details": details, **extra}, status=status)


def _from(exc: EInvoiceError):
    return _err(exc.code, exc.details, exc.status, **exc.extra)


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


class EInvoiceView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def gate(self, request, org_id, perm=VIEW):
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        if not services.flag_on(request.user, org):
            return org, _err("not_implemented", "E-invoicing is not enabled", 501)
        if perm and not can(request.user, perm, org):
            raise PermissionDenied(f"Missing permission: {perm}")
        return org, None

    def invoice(self, org, invoice_id):
        return get_object_or_404(Invoice.objects.prefetch_related("lines"), org=org, pk=invoice_id)


def _country(value):
    value = str(value or "").upper()
    return value if value in (SA, EG) else None


class MetaView(EInvoiceView):
    @extend_schema(summary="E-invoicing settings summary for the screens")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        manager = can(request.user, MANAGE, org)
        profiles = {c: services.profile_payload(services.profile_for(org, c), manager) for c in (SA, EG)}
        from integrations import crypto

        return Response(
            {
                "can_issue": can(request.user, ISSUE, org),
                "can_manage": manager,
                "is_admin": is_org_owner_or_admin(request.user, org),
                "profiles": profiles,
                "chain": services.chain_ok(org),
                "secrets_available": crypto.is_configured(),
                "demo": services.demo_allowed(org),
                "sa_categories": ["S", "Z", "E", "O"],
                "eg_subtypes": [f"V{n:03d}" for n in range(1, 11)],
                "environments": {SA: ["sandbox", "simulation", "production"], EG: ["preprod", "production"]},
            }
        )


class SettingsView(EInvoiceView):
    @extend_schema(summary="Save seller details and authority settings for a country")
    def put(self, request, org_id, country):
        org, error = self.gate(request, org_id, MANAGE)
        if error:
            return error
        country = _country(country)
        if country is None:
            return _err("invalid", "Country is SA or EG")
        try:
            profile = services.update_profile(request.user, org, country, _body(request))
        except EInvoiceError as exc:
            return _from(exc)
        return Response(services.profile_payload(profile, True))


class ZatcaStepView(EInvoiceView):
    STEPS = {"key", "compliance", "checks", "production", "reset"}

    @extend_schema(summary="Run one ZATCA onboarding step")
    def post(self, request, org_id, step):
        org, error = self.gate(request, org_id, MANAGE)
        if error:
            return error
        if step not in self.STEPS:
            return _err("not_found", "Unknown step", 404)
        try:
            if step == "key":
                profile = onboarding.generate_key(request.user, org)
            elif step == "compliance":
                profile = onboarding.compliance_csid(request.user, org, str(_body(request).get("otp") or ""))
            elif step == "checks":
                profile = onboarding.compliance_checks(request.user, org)
            elif step == "production":
                profile = onboarding.production_csid(request.user, org)
            else:
                profile = onboarding.reset(request.user, org)
        except EInvoiceError as exc:
            return _from(exc)
        return Response(services.profile_payload(profile, True))


class ZatcaCsrView(EInvoiceView):
    @extend_schema(summary="The CSR (public) for checking its fields")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id, MANAGE)
        if error:
            return error
        profile = services.profile_for(org, SA)
        if profile is None or not profile.csr_pem:
            return _err("not_found", "No CSR yet", 404)
        return Response({"csr": profile.csr_pem})


class EtaCheckView(EInvoiceView):
    @extend_schema(summary="Check the ETA client credentials")
    def post(self, request, org_id):
        org, error = self.gate(request, org_id, MANAGE)
        if error:
            return error
        try:
            return Response(onboarding.eta_check(request.user, org))
        except EInvoiceError as exc:
            return _from(exc)


class ResidencyView(EInvoiceView):
    @extend_schema(summary="Where this org's data lives, by kind")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        out = residency.report(org)
        out["can_change"] = can(request.user, MANAGE, org) and is_org_owner_or_admin(request.user, org)
        return Response(out)

    @extend_schema(summary="Choose and pin the data region (owner or admin with einvoice.manage)")
    def patch(self, request, org_id):
        org, error = self.gate(request, org_id, MANAGE)
        if error:
            return error
        if not is_org_owner_or_admin(request.user, org):
            raise PermissionDenied("Only an org owner or admin can change this")
        data = _body(request)
        region = str(data.get("region") or "")
        if region and region not in residency.REGIONS:
            return _err("invalid", "Pick one of the listed regions")
        if "pinned" in data and not isinstance(data.get("pinned"), bool):
            return _err("invalid", "pinned must be true or false")
        with transaction.atomic():
            org = Organization.objects.select_for_update().get(pk=org.pk)
            current = dict((org.settings or {}).get("data_region") or {})
            if "region" in data:
                current["region"] = region
            if "pinned" in data:
                current["pinned"] = bool(data["pinned"]) and bool(current.get("region"))
            settings_value = dict(org.settings or {})
            settings_value["data_region"] = current
            org.settings = settings_value
            org.save(update_fields=["settings"])
        audit(request.user, "org.data_region_changed", target=org, payload={"region": current.get("region", ""), "pinned": current.get("pinned", False)}, org=org)
        out = residency.report(org)
        out["can_change"] = True
        return Response(out)


class InvoiceListView(EInvoiceView):
    @extend_schema(summary="E-invoices (filter by country and status)")
    def get(self, request, org_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        qs = Invoice.objects.filter(org=org).select_related("proposal")
        country = _country(request.query_params.get("country"))
        if country:
            qs = qs.filter(country=country)
        status = request.query_params.get("status")
        if status in dict(Invoice.STATUSES):
            qs = qs.filter(status=status)
        return Response([services.invoice_payload(i) for i in qs[:MAX_LIST]])

    @extend_schema(summary="Create a draft e-invoice (totals are computed on the server)")
    def post(self, request, org_id):
        org, error = self.gate(request, org_id, ISSUE)
        if error:
            return error
        try:
            invoice = services.save_invoice(request.user, org, _body(request))
        except EInvoiceError as exc:
            return _from(exc)
        audit(request.user, "einvoice.created", target=invoice, payload={"country": invoice.country, "number": invoice.number}, org=org)
        return Response(services.invoice_payload(invoice, detail=True), status=201)


class ImportView(EInvoiceView):
    @extend_schema(summary="Start a draft from an Odoo or Zoho Books invoice")
    def post(self, request, org_id):
        org, error = self.gate(request, org_id, ISSUE)
        if error:
            return error
        data = _body(request)
        country = _country(data.get("country"))
        if country is None:
            return _err("invalid", "Country is SA or EG")
        try:
            fields = sources.fetch(request.user, org, str(data.get("provider") or ""), str(data.get("ref") or ""), country)
            fields.update({"country": country, "invoice_type": data.get("invoice_type") or ("standard" if country == SA else "b2b")})
            if not fields.get("currency"):
                fields.pop("currency", None)
            provider = str(data.get("provider"))
            invoice = services.save_invoice(request.user, org, fields, source=provider, source_ref=str(data.get("ref") or ""))
        except EInvoiceError as exc:
            return _from(exc)
        audit(request.user, "einvoice.imported", target=invoice, payload={"provider": provider, "number": invoice.number}, org=org)
        return Response(services.invoice_payload(invoice, detail=True), status=201)


class InvoiceDetailView(EInvoiceView):
    @extend_schema(summary="One e-invoice with lines, totals, QR and the authority's answer")
    def get(self, request, org_id, invoice_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        return Response(services.invoice_payload(self.invoice(org, invoice_id), detail=True))

    @extend_schema(summary="Change a draft")
    def patch(self, request, org_id, invoice_id):
        org, error = self.gate(request, org_id, ISSUE)
        if error:
            return error
        invoice = self.invoice(org, invoice_id)
        try:
            invoice = services.save_invoice(request.user, org, _body(request), invoice)
        except EInvoiceError as exc:
            return _from(exc)
        return Response(services.invoice_payload(invoice, detail=True))

    @extend_schema(summary="Delete a draft (its creator or an e-invoicing manager)")
    def delete(self, request, org_id, invoice_id):
        org, error = self.gate(request, org_id, ISSUE)
        if error:
            return error
        invoice = self.invoice(org, invoice_id)
        if invoice.status != Invoice.DRAFT:
            return _err("conflict", "Only drafts can be deleted", 409)
        if invoice.created_by_id != request.user.id and not can(request.user, MANAGE, org):
            raise PermissionDenied("Only its creator or an e-invoicing manager can delete this draft")
        audit(request.user, "einvoice.deleted", target=invoice, payload={"number": invoice.number}, org=org)
        invoice.delete()
        return Response(status=204)


class InvoiceActionView(EInvoiceView):
    @extend_schema(summary="prepare | submit | poll | copy")
    def post(self, request, org_id, invoice_id, action):
        org, error = self.gate(request, org_id, ISSUE)
        if error:
            return error
        invoice = self.invoice(org, invoice_id)
        try:
            if action == "prepare":
                invoice = services.prepare(request.user, org, invoice.id)
            elif action == "submit":
                proposal = services.request_submission(request.user, org, invoice)
                from actions.service import payload

                return Response({"approval": payload(proposal), "invoice": services.invoice_payload(invoice, detail=True)}, status=201)
            elif action == "poll":
                invoice = services.poll(request.user, org, invoice)
            elif action == "copy":
                invoice = services.copy_as_draft(request.user, org, invoice)
                return Response(services.invoice_payload(invoice, detail=True), status=201)
            else:
                return _err("not_found", "Unknown action", 404)
        except EInvoiceError as exc:
            return _from(exc)
        invoice = self.invoice(org, invoice.id)
        return Response(services.invoice_payload(invoice, detail=True))


class ApprovalView(EInvoiceView):
    @extend_schema(summary="Approve or reject your own pending approval to send this invoice")
    def post(self, request, org_id, invoice_id, decision):
        org, error = self.gate(request, org_id, ISSUE)
        if error:
            return error
        if decision not in ("approve", "reject"):
            return _err("not_found", "Unknown decision", 404)
        invoice = self.invoice(org, invoice_id)
        proposal = services.pending_proposal(invoice)
        if proposal is None:
            return _err("not_found", "Nothing is waiting for approval", 404)
        from actions import service

        try:
            if decision == "approve":
                proposal = service.approve(proposal.id, request.user, org)
            else:
                proposal = service.reject(proposal.id, request.user, org)
        except service.ActionDenied as exc:
            status = 404 if exc.code in ("not_found",) else 409 if exc.code in ("not_pending", "expired", "not_available") else 403
            return _err(exc.code, str(exc), status)
        invoice = self.invoice(org, invoice_id)
        return Response({"approval": service.payload(proposal), "invoice": services.invoice_payload(invoice, detail=True)})


class XmlView(EInvoiceView):
    @extend_schema(summary="The signed XML (or the XML ZATCA cleared)")
    def get(self, request, org_id, invoice_id):
        org, error = self.gate(request, org_id)
        if error:
            return error
        invoice = self.invoice(org, invoice_id)
        cleared = request.query_params.get("cleared") == "1"
        xml = invoice.cleared_xml if cleared else invoice.xml
        if not xml:
            return _err("not_found", "No XML yet", 404)
        return Response({"filename": f"{invoice.number}{'-cleared' if cleared else ''}.xml", "xml": xml, "simulated": invoice.simulated and cleared})


class EtaDocumentView(EInvoiceView):
    @extend_schema(summary="The ETA document and the exact text your token signs")
    def get(self, request, org_id, invoice_id):
        org, error = self.gate(request, org_id, ISSUE)
        if error:
            return error
        invoice = self.invoice(org, invoice_id)
        if invoice.country != EG or not invoice.eta_document:
            return _err("not_found", "Prepare the invoice first", 404)
        canonical = services.eta_canonical(invoice)
        from einvoice.eta.serialize import sha256_hex

        return Response({"document": invoice.eta_document, "canonical": canonical, "sha256": sha256_hex(canonical), "filename": f"{invoice.number}-to-sign.txt"})


class SignatureView(EInvoiceView):
    @extend_schema(summary="Upload the CAdES-BES signature made with your token (manual mode)")
    def post(self, request, org_id, invoice_id):
        org, error = self.gate(request, org_id, ISSUE)
        if error:
            return error
        invoice = self.invoice(org, invoice_id)
        try:
            invoice = services.upload_signature(request.user, org, invoice, str(_body(request).get("signature") or ""))
        except EInvoiceError as exc:
            return _from(exc)
        return Response(services.invoice_payload(invoice, detail=True))

