from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from core_v2.views import V2APIView
from organizations.models import Organization
from organizations.permissions import HasPerm, IsActiveOrgMember, is_org_owner_or_admin
from organizations.flags import effective_flag
from organizations.models import OrgMembership
from telemetry.models import Budget, UsageEvent
from telemetry.pricing import month_spend


def _token_state(row):
    if row.estimated:
        return "estimated"
    if row.total_tokens is None:
        return "unknown"
    return "measured"


def _row_payload(row):
    return {
        "id": str(row.id),
        "user_id": str(row.user_id) if row.user_id else None,
        "model": row.model,
        "operation": row.operation,
        "total_tokens": row.total_tokens,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "token_state": _token_state(row),
        "estimated": row.estimated,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }


class UsageListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="List AI usage for this org or the current member")
    def get(self, request, org_id):
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        HasPerm("ai.usage.view").has_permission(request, self)
        qs = UsageEvent.objects.filter(org=org).order_by("-created_at")
        if not is_org_owner_or_admin(request.user, org):
            qs = qs.filter(user=request.user)
        return Response({"results": [_row_payload(row) for row in qs[:100]]})


def _org(org_id):
    return get_object_or_404(Organization, pk=org_id, is_active=True)


def _budgets_flag(org, user) -> bool:
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    return effective_flag(org, membership, "budgets", default=False)


class BudgetView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Read the org AI budget")
    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("budget.view").has_permission(request, self)
        if not _budgets_flag(org, request.user):
            return Response({"error": "not_implemented", "details": "Budgets are not implemented"}, status=501)
        budget = Budget.objects.filter(org=org).first()
        if budget is None:
            return Response({"cap_amount": None, "currency": "USD", "period": "month"})
        return Response(
            {
                "id": str(budget.id),
                "cap_amount": str(budget.cap_amount),
                "currency": budget.currency,
                "period": budget.period,
            }
        )

    @extend_schema(summary="Set the org AI budget")
    def put(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("budget.manage").has_permission(request, self)
        if not _budgets_flag(org, request.user):
            return Response({"error": "not_implemented", "details": "Budgets are not implemented"}, status=501)
        cap = (request.data or {}).get("cap_amount")
        if cap is None:
            return Response({"error": "invalid", "details": "cap_amount is required"}, status=400)
        budget, _ = Budget.objects.update_or_create(
            org=org,
            period=Budget.PERIOD_MONTH,
            defaults={"cap_amount": cap, "currency": (request.data or {}).get("currency") or "USD"},
        )
        return Response(
            {
                "id": str(budget.id),
                "cap_amount": str(budget.cap_amount),
                "currency": budget.currency,
                "period": budget.period,
            }
        )


class BudgetStatusView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Read current platform spend against the cap")
    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("budget.view").has_permission(request, self)
        if not _budgets_flag(org, request.user):
            return Response({"error": "not_implemented", "details": "Budgets are not implemented"}, status=501)
        budget = Budget.objects.filter(org=org).first()
        spent = month_spend(org)
        return Response(
            {
                "spent": str(spent),
                "cap_amount": str(budget.cap_amount) if budget else None,
                "currency": budget.currency if budget else "USD",
            }
        )
