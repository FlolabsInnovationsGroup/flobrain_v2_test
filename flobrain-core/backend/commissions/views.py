"""Leads and commission (Phase 12, flag ``commissions``; a member flag can switch it off per person).

Members submit and move their own leads. Only ``commissions.manage`` (owner and admins by default)
records commissions and changes their amount or status; every change is audited with before/after.
"""

import re
import uuid
from decimal import Decimal, InvalidOperation

from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from commissions.models import Commission, Lead
from core_v2.views import V2APIView
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization
from organizations.permissions import IsActiveOrgMember
from organizations.permissions.engine import can
from organizations.services.core import audit

FLAG = "commissions"
CURRENCY = re.compile(r"^[A-Z]{3}$")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[A-Za-z]{2,}$")


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def _bad(details):
    return Response({"error": "invalid", "details": details}, status=400)


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _money(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < 0 or amount > Decimal("9999999999.99"):
        return None
    return amount.quantize(Decimal("0.01"))


def _gate(request, org_id):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, FLAG, default=False):
        return org, Response({"error": "not_implemented", "details": "Leads and commission are not enabled"}, status=501)
    return org, None


def _manager(request, org):
    return can(request.user, "commissions.manage", org)


def _lead_payload(lead):
    return {
        "id": str(lead.id),
        "owner": {"id": str(lead.owner_user_id), "name": lead.owner_user.username},
        "project_or_product": lead.project_or_product,
        "contact_name": lead.contact_name,
        "contact_email": lead.contact_email,
        "stage": lead.stage,
        "estimated_value": str(lead.estimated_value) if lead.estimated_value is not None else None,
        "notes": lead.notes,
        "created_at": lead.created_at.isoformat(),
    }


def _commission_payload(c):
    return {
        "id": str(c.id),
        "lead": str(c.lead_id) if c.lead_id else None,
        "lead_name": c.lead.contact_name if c.lead_id else "",
        "user": {"id": str(c.user_id), "name": c.user.username},
        "amount": str(c.amount),
        "currency": c.currency,
        "status": c.status,
        "updated_at": c.updated_at.isoformat(),
    }


def _apply_lead_fields(lead, data):
    if "project_or_product" in data:
        lead.project_or_product = str(data["project_or_product"] or "").strip()[:160]
    if "contact_name" in data:
        lead.contact_name = str(data["contact_name"] or "").strip()[:160]
    if "contact_email" in data:
        email = str(data["contact_email"] or "").strip()
        if email and not EMAIL.fullmatch(email):
            raise ValueError("contact_email is not an email address")
        lead.contact_email = email or None
    if "stage" in data:
        if data["stage"] not in Lead.STAGES:
            raise ValueError("stage must be contacted, meeting_1, in_progress, won or lost")
        lead.stage = data["stage"]
    if "estimated_value" in data:
        if data["estimated_value"] in (None, ""):
            lead.estimated_value = None
        else:
            value = _money(data["estimated_value"])
            if value is None:
                raise ValueError("estimated_value must be a positive amount")
            lead.estimated_value = value
    if "notes" in data:
        lead.notes = str(data["notes"] or "")[:4000]
    if not lead.project_or_product or not lead.contact_name:
        raise ValueError("project_or_product and contact_name are required")


class LeadListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Leads (my own; commissions.manage sees all)")
    def get(self, request, org_id):
        org, err = _gate(request, org_id)
        if err:
            return err
        qs = Lead.objects.filter(org=org).select_related("owner_user")
        if not _manager(request, org):
            qs = qs.filter(owner_user=request.user)
        stage = request.query_params.get("stage")
        if stage in Lead.STAGES:
            qs = qs.filter(stage=stage)
        return Response([_lead_payload(lead) for lead in qs.order_by("-created_at")[:500]])

    @extend_schema(summary="Submit a lead")
    def post(self, request, org_id):
        org, err = _gate(request, org_id)
        if err:
            return err
        lead = Lead(org=org, owner_user=request.user)
        try:
            _apply_lead_fields(lead, _body(request))
        except ValueError as exc:
            return _bad(str(exc))
        lead.save()
        audit(request.user, "lead.create", target=lead, request=request, org=org)
        return Response(_lead_payload(lead), status=201)


class LeadDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Move or edit a lead (its owner or commissions.manage)")
    def patch(self, request, org_id, lead_id):
        org, err = _gate(request, org_id)
        if err:
            return err
        lead = get_object_or_404(Lead.objects.select_related("owner_user"), pk=lead_id, org=org)
        if lead.owner_user_id != request.user.id and not _manager(request, org):
            return Response({"error": "not_found"}, status=404)
        before = lead.stage
        try:
            _apply_lead_fields(lead, _body(request))
        except ValueError as exc:
            return _bad(str(exc))
        lead.save()
        audit(request.user, "lead.update", target=lead, payload={"stage_before": before, "stage": lead.stage}, request=request, org=org)
        return Response(_lead_payload(lead))


class CommissionListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Commissions (my own; commissions.manage sees all)")
    def get(self, request, org_id):
        org, err = _gate(request, org_id)
        if err:
            return err
        qs = Commission.objects.filter(org=org).select_related("lead", "user")
        if not _manager(request, org):
            qs = qs.filter(user=request.user)
        return Response([_commission_payload(c) for c in qs.order_by("-created_at")[:500]])

    @extend_schema(summary="Record a commission for a lead (commissions.manage)")
    def post(self, request, org_id):
        org, err = _gate(request, org_id)
        if err:
            return err
        if not _manager(request, org):
            return Response({"error": "permission_denied", "details": "Only the owner and admins record commissions"}, status=403)
        data = _body(request)
        lead = Lead.objects.filter(org=org, pk=_uuid(data.get("lead"))).first()
        amount = _money(data.get("amount"))
        currency = str(data.get("currency") or "USD").upper()
        if lead is None:
            return Response({"error": "not_found", "details": "Lead not found"}, status=404)
        if amount is None or not CURRENCY.fullmatch(currency):
            return _bad("amount (positive) and a 3-letter currency are required")
        if lead.owner_user_id == request.user.id and not OrgMembership.objects.filter(org=org, user=request.user, org_role=OrgMembership.ORG_ROLE_OWNER).exists():
            return Response({"error": "permission_denied", "details": "Someone else records your own commission"}, status=403)
        c = Commission.objects.create(org=org, lead=lead, user=lead.owner_user, amount=amount, currency=currency, recorded_by=request.user)
        audit(request.user, "commission.create", target=c, payload={"amount": str(amount), "currency": currency}, request=request, org=org)
        return Response(_commission_payload(c), status=201)


class CommissionDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Change a commission's amount or status (commissions.manage, audited)")
    def patch(self, request, org_id, commission_id):
        org, err = _gate(request, org_id)
        if err:
            return err
        if not _manager(request, org):
            return Response({"error": "permission_denied", "details": "Only the owner and admins change commissions"}, status=403)
        c = get_object_or_404(Commission.objects.select_related("lead", "user"), pk=commission_id, org=org)
        if c.user_id == request.user.id and not OrgMembership.objects.filter(org=org, user=request.user, org_role=OrgMembership.ORG_ROLE_OWNER).exists():
            return Response({"error": "permission_denied", "details": "Someone else changes your own commission"}, status=403)
        data = _body(request)
        before = {"amount": str(c.amount), "status": c.status}
        if "amount" in data:
            amount = _money(data["amount"])
            if amount is None:
                return _bad("amount must be a positive amount")
            c.amount = amount
        if "status" in data:
            if data["status"] not in Commission.STATUSES:
                return _bad(f"status must be one of {', '.join(Commission.STATUSES)}")
            c.status = data["status"]
        c.save()
        audit(request.user, "commission.update", target=c, payload={"before": before, "after": {"amount": str(c.amount), "status": c.status}}, request=request, org=org)
        return Response(_commission_payload(c))


class CommissionSummaryView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Earned, pending, referrals sent and conversion rate (mine, or ?user= for managers)")
    def get(self, request, org_id):
        org, err = _gate(request, org_id)
        if err:
            return err
        user_id = request.user.id
        if request.query_params.get("user") and _manager(request, org):
            user_id = _uuid(request.query_params["user"]) or user_id
        money = Commission.objects.filter(org=org, user_id=user_id).values("currency").annotate(
            earned=Sum("amount", filter=Q(status__in=Commission.EARNED)),
            pending=Sum("amount", filter=Q(status__in=Commission.WAITING)),
        )
        leads = Lead.objects.filter(org=org, owner_user_id=user_id).aggregate(total=Count("id"), won=Count("id", filter=Q(stage="won")))
        fmt = lambda d: str(Decimal(d or 0).quantize(Decimal("0.01")))  # noqa: E731
        by_currency = {row["currency"]: {"earned": fmt(row["earned"]), "pending": fmt(row["pending"])} for row in money}
        first = next(iter(by_currency.values()), {"earned": "0.00", "pending": "0.00"})
        currency = next(iter(by_currency), "USD")
        return Response(
            {
                "earned": f"{first['earned']} {currency}",
                "pending": f"{first['pending']} {currency}",
                "by_currency": by_currency,
                "referrals_sent": leads["total"],
                "won": leads["won"],
                "conversion_rate": round(leads["won"] / leads["total"], 3) if leads["total"] else None,
            }
        )
