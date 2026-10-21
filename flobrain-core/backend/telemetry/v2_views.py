"""AI usage and budgets (Phase 7, spec 6.19 and 8.3).

Usage: ``GET /orgs/{org}/usage`` (rows), ``GET …/usage/summary?days=&group=`` (totals per
member, team, model or surface), ``GET …/usage/export?days=`` (CSV). Owners and admins see the
org, team leads see the members of the teams they lead, everyone else sees their own rows.

Budgets: ``GET/PUT /orgs/{org}/budgets`` (the org budget, kept for older callers, plus every
budget in ``results``), ``POST …/budgets`` (a team or member budget), ``PATCH/DELETE
…/budgets/{id}``, ``GET …/budgets/status`` (spend per budget), ``GET …/budgets/mine`` (budgets
that apply to me: my own, and my teams' when I lead them). Flag ``budgets`` (501 when off).
"""

import csv
import io
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from core_v2.views import V2APIView
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from organizations.permissions import HasPerm, IsActiveOrgMember, can, is_org_owner_or_admin
from organizations.services.core import audit
from telemetry.models import Budget, UsageEvent
from telemetry.pricing import PriceBook, budget_spend, maybe_alert, money_for_event, scope_label, state_for

MAX_LIMIT = Decimal("100000000")
EXPORT_MAX_ROWS = 50000


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


def _org(org_id):
    return get_object_or_404(Organization, pk=org_id, is_active=True)


def _usage_scope(user, org):
    """(queryset, scope) of usage rows this person may read."""
    qs = UsageEvent.objects.filter(org=org)
    if is_org_owner_or_admin(user, org):
        return qs, "org"
    led = list(
        TeamMembership.objects.filter(team__org=org, user=user, team_role=TeamMembership.ROLE_LEAD).values_list(
            "team_id", flat=True
        )
    )
    if led:
        members = set(TeamMembership.objects.filter(team_id__in=led).values_list("user_id", flat=True)) | {user.id}
        return qs.filter(user_id__in=members), "teams"
    return qs.filter(user=user), "own"


PRIVATE_KEY, PRIVATE_LABEL = "private", "People who keep their insights personal"
TEAM_KEY, TEAM_LABEL = "team_members", "Your team members (combined)"


def private_users(org) -> set:
    """People who chose "keep my insights personal": never a row of their own in org analytics."""
    from privacy.models import PrivacySettings

    return set(PrivacySettings.objects.filter(org=org, analytics_personal_only=True).values_list("user_id", flat=True))


def _days(request, default=30):
    try:
        return max(1, min(366, int(request.query_params.get("days", default))))
    except (TypeError, ValueError):
        return default


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


GROUPS = ("member", "team", "model", "surface")


def _names(org, user_ids, team_ids):
    from users.models import User

    users = {u.id: (u.username or u.email) for u in User.objects.filter(pk__in=user_ids).only("username", "email")}
    teams = {t.id: t.name for t in Team.objects.filter(org=org, pk__in=team_ids).only("name")}
    return users, teams


def _surface(row):
    return row.surface or ("render" if row.operation == "render" else "other")


class UsageSummaryView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Tokens and cost per member, team, model or surface; platform and own keys apart")
    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("ai.usage.view").has_permission(request, self)
        group = request.query_params.get("group", "member")
        if group not in GROUPS:
            return Response({"error": "invalid", "details": "group must be member, team, model or surface"}, status=400)
        days = _days(request)
        since = timezone.now() - timedelta(days=days)
        qs, scope = _usage_scope(request.user, org)
        rows = list(
            qs.filter(created_at__gte=since).only(
                "user_id", "team_id", "provider", "model", "surface", "operation", "credential_source", "status",
                "input_tokens", "output_tokens", "total_tokens", "created_at",
            )
        )
        book = PriceBook()
        users, teams = _names(org, {r.user_id for r in rows if r.user_id}, {r.team_id for r in rows if r.team_id})
        private = private_users(org) - {request.user.id}
        out, totals = {}, _bucket("all", "All")
        for row in rows:
            if group == "member" and row.user_id == request.user.id:
                key, label = str(row.user_id), users.get(row.user_id, "")
            elif group == "member" and scope == "teams":
                # Leads see their team's AI use together, never per person (privacy promise).
                key, label = TEAM_KEY, TEAM_LABEL
            elif group == "member" and row.user_id in private:
                key, label = PRIVATE_KEY, PRIVATE_LABEL
            elif group == "member":
                key, label = str(row.user_id or ""), users.get(row.user_id, "") if row.user_id else ""
            elif group == "team":
                key, label = str(row.team_id or ""), teams.get(row.team_id, "") if row.team_id else ""
            elif group == "model":
                key, label = f"{row.provider}/{row.model}", row.model or ""
            else:
                key = label = _surface(row)
            bucket = out.setdefault(key, _bucket(key, label))
            for b in (bucket, totals):
                _add(b, row, book)
        results = sorted((_finish(b) for b in out.values()), key=lambda b: (-b["total_tokens"], b["label"]))
        return Response({"days": days, "group": group, "scope": scope, "totals": _finish(totals), "results": results})


def _bucket(key, label):
    return {
        "key": key,
        "label": label,
        "calls": 0,
        "errors": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "platform_calls": 0,
        "platform_tokens": 0,
        "platform_cost": Decimal("0"),
        "unpriced_calls": 0,
        "own_key_calls": 0,
        "own_key_tokens": 0,
    }


def _add(bucket, row, book):
    tokens = row.total_tokens or 0
    bucket["calls"] += 1
    bucket["errors"] += row.status != "ok"
    bucket["input_tokens"] += row.input_tokens or 0
    bucket["output_tokens"] += row.output_tokens or 0
    bucket["total_tokens"] += tokens
    if row.credential_source == UsageEvent.CREDENTIAL_PLATFORM:
        bucket["platform_calls"] += 1
        bucket["platform_tokens"] += tokens
        amount = money_for_event(row, book)
        if amount is None:
            bucket["unpriced_calls"] += 1
        else:
            bucket["platform_cost"] += amount
    else:
        bucket["own_key_calls"] += 1
        bucket["own_key_tokens"] += tokens


def _finish(bucket):
    return {**bucket, "platform_cost": str(bucket["platform_cost"].quantize(Decimal("0.0001")))}


class UsageExportView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Download AI usage as CSV (same scope as the summary)")
    def get(self, request, org_id):
        from console.impersonation import is_impersonated

        org = _org(org_id)
        request.org = org
        HasPerm("ai.usage.view").has_permission(request, self)
        if is_impersonated(request):
            raise PermissionDenied("Exports are not available during support access")
        days = _days(request)
        since = timezone.now() - timedelta(days=days)
        qs, scope = _usage_scope(request.user, org)
        if scope == "teams":
            raise PermissionDenied("Team leads see team totals on the usage page; the per-call export is for owners and admins")
        rows = list(qs.filter(created_at__gte=since).order_by("-created_at")[:EXPORT_MAX_ROWS])
        users, teams = _names(org, {r.user_id for r in rows if r.user_id}, {r.team_id for r in rows if r.team_id})
        for uid in private_users(org) - {request.user.id}:
            users[uid] = "Private"
        book = PriceBook()
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["time", "member", "team", "provider", "model", "surface", "operation", "key", "status",
             "input_tokens", "output_tokens", "total_tokens", "token_state", "platform_cost"]
        )
        for row in rows:
            cost = money_for_event(row, book)
            writer.writerow([
                row.created_at.isoformat(),
                _cell(users.get(row.user_id, "")),
                _cell(teams.get(row.team_id, "")),
                _cell(row.provider),
                _cell(row.model),
                _surface(row),
                row.operation,
                "own key" if row.credential_source != UsageEvent.CREDENTIAL_PLATFORM else "platform",
                _cell(row.status),
                "" if row.input_tokens is None else row.input_tokens,
                "" if row.output_tokens is None else row.output_tokens,
                "" if row.total_tokens is None else row.total_tokens,
                _token_state(row),
                "" if cost is None else str(cost.quantize(Decimal("0.000001"))),
            ])
        audit(request.user, "usage.export", target=org, payload={"days": days, "rows": len(rows)}, request=request, org=org)
        response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="ai-usage-{org.slug}-{days}d.csv"'
        return response


def _cell(value):
    """Spreadsheet-safe text: a leading = + - @ would be read as a formula."""
    text = str(value or "")
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


# --- budgets ----------------------------------------------------------------------


def _budgets_flag(org, user) -> bool:
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    return effective_flag(org, membership, "budgets", default=False)


def _off():
    return Response({"error": "not_implemented", "details": "Budgets are not implemented"}, status=501)


def _bad(details):
    return Response({"error": "invalid", "details": details}, status=400)


def _budget_payload(budget, spent=None):
    data = {
        "id": str(budget.id),
        "scope_type": budget.scope_type,
        "scope_id": str(budget.scope_id) if budget.scope_id else None,
        "scope_name": scope_label(budget),
        "cap_amount": str(budget.cap_amount),
        "limit_amount": str(budget.cap_amount),
        "currency": budget.currency,
        "period": budget.period,
        "on_exceed": budget.on_exceed,
        "downgrade_model": budget.downgrade_model or None,
        "alert_threshold": str(budget.alert_threshold),
    }
    if spent is not None:
        data["spent"] = str(spent.quantize(Decimal("0.0001")))
        data["ratio"] = float(spent / budget.cap_amount) if budget.cap_amount > 0 else (1.0 if spent > 0 else 0.0)
        data["state"] = state_for(budget, spent)
    return data


def _parse_limit(data):
    raw = data.get("limit_amount", data.get("cap_amount"))
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        value = None
    if raw is None or value is None or not value.is_finite() or value < 0 or value > MAX_LIMIT:
        raise ValueError("cap_amount must be a number between 0 and 100000000")
    return value.quantize(Decimal("0.0001"))


def _parse_currency(data, default="USD"):
    currency = str(data.get("currency") or default).upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("currency must be a 3-letter code")
    return currency


def _downgrade_models(org):
    """Platform models a budget may switch to (the direct allowlist; the demo model in demo mode)."""
    from brain.llm import demo_ai, direct

    models = list(direct.allowlist())
    if demo_ai.enabled():
        models.append(demo_ai.MODEL)
    return models


def _apply_behaviour(budget, data, org):
    if "on_exceed" in data:
        if data["on_exceed"] not in (Budget.ON_BLOCK, Budget.ON_DOWNGRADE, Budget.ON_ALERT):
            raise ValueError("on_exceed must be block, downgrade or alert_only")
        budget.on_exceed = data["on_exceed"]
    if "downgrade_model" in data:
        budget.downgrade_model = str(data.get("downgrade_model") or "").strip()[:128]
    if budget.on_exceed == Budget.ON_DOWNGRADE:
        if not budget.downgrade_model:
            raise ValueError("downgrade_model is required when on_exceed is downgrade")
        if budget.downgrade_model not in _downgrade_models(org):
            raise ValueError("downgrade_model must be one of the platform models")
        from brain.llm.policy import check_ai

        if check_ai(org, "direct"):
            raise ValueError("this organization only allows self-hosted models, and the platform model is not one")
    else:
        budget.downgrade_model = ""
    if "alert_threshold" in data:
        try:
            threshold = Decimal(str(data["alert_threshold"]))
        except (InvalidOperation, TypeError, ValueError):
            threshold = None
        if threshold is None or not threshold.is_finite() or threshold < Decimal("0.05") or threshold > Decimal("1"):
            raise ValueError("alert_threshold must be between 0.05 and 1")
        budget.alert_threshold = threshold.quantize(Decimal("0.01"))


def _budget_gate(request, view, org_id, perm):
    org = _org(org_id)
    request.org = org
    HasPerm(perm).has_permission(request, view)
    return org, (None if _budgets_flag(org, request.user) else _off())


class BudgetView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Read the org AI budget (and every team and member budget in results)")
    def get(self, request, org_id):
        org, error = _budget_gate(request, self, org_id, "budget.view")
        if error:
            return error
        rows = list(Budget.objects.filter(org=org).select_related("org"))
        org_budget = next((b for b in rows if b.scope_type == Budget.SCOPE_ORG), None)
        base = (
            _budget_payload(org_budget)
            if org_budget
            else {"cap_amount": None, "currency": "USD", "period": "month"}
        )
        order = {Budget.SCOPE_ORG: 0, Budget.SCOPE_TEAM: 1, Budget.SCOPE_USER: 2}
        base["results"] = [_budget_payload(b) for b in sorted(rows, key=lambda b: (order[b.scope_type], scope_label(b)))]
        base["downgrade_models"] = _downgrade_models(org)
        return Response(base)

    @extend_schema(summary="Set the org AI budget")
    def put(self, request, org_id):
        org, error = _budget_gate(request, self, org_id, "budget.manage")
        if error:
            return error
        data = request.data if isinstance(request.data, dict) else {}
        try:
            cap = _parse_limit(data)
            currency = _parse_currency(data)
        except ValueError as exc:
            return _bad(str(exc))
        budget = Budget.objects.filter(org=org, scope_type=Budget.SCOPE_ORG, period=Budget.PERIOD_MONTH).first()
        budget = budget or Budget(org=org, scope_type=Budget.SCOPE_ORG, period=Budget.PERIOD_MONTH)
        if budget.cap_amount != cap:
            budget.alerted_period = ""  # a new limit gets its own alert
        budget.cap_amount, budget.currency = cap, currency
        try:
            _apply_behaviour(budget, data, org)
        except ValueError as exc:
            return _bad(str(exc))
        budget.save()
        audit(request.user, "budget.set", target=budget, payload=_audit_payload(budget), request=request, org=org)
        return Response(_budget_payload(budget))

    @extend_schema(summary="Add a team or member budget (or the org budget when there is none)")
    def post(self, request, org_id):
        org, error = _budget_gate(request, self, org_id, "budget.manage")
        if error:
            return error
        data = request.data if isinstance(request.data, dict) else {}
        scope_type = data.get("scope_type")
        if scope_type not in (Budget.SCOPE_ORG, Budget.SCOPE_TEAM, Budget.SCOPE_USER):
            return _bad("scope_type must be org, team or user")
        scope_id = None
        if scope_type == Budget.SCOPE_TEAM:
            team = Team.objects.filter(org=org, pk=_uuid(data.get("scope_id"))).first()
            if team is None:
                return Response({"error": "not_found", "details": "Team not found"}, status=404)
            scope_id = team.id
        elif scope_type == Budget.SCOPE_USER:
            membership = OrgMembership.objects.filter(org=org, user_id=_uuid(data.get("scope_id"))).first()
            if membership is None:
                return Response({"error": "not_found", "details": "Member not found"}, status=404)
            scope_id = membership.user_id
        if Budget.objects.filter(org=org, scope_type=scope_type, scope_id=scope_id, period=Budget.PERIOD_MONTH).exists():
            return Response({"error": "exists", "details": "This scope already has a budget"}, status=409)
        budget = Budget(org=org, scope_type=scope_type, scope_id=scope_id, period=Budget.PERIOD_MONTH)
        try:
            budget.cap_amount = _parse_limit(data)
            budget.currency = _parse_currency(data)
            _apply_behaviour(budget, data, org)
        except ValueError as exc:
            return _bad(str(exc))
        budget.save()
        audit(request.user, "budget.create", target=budget, payload=_audit_payload(budget), request=request, org=org)
        return Response(_budget_payload(budget), status=201)


def _audit_payload(budget):
    return {
        "scope_type": budget.scope_type,
        "scope_id": str(budget.scope_id) if budget.scope_id else None,
        "cap_amount": str(budget.cap_amount),
        "currency": budget.currency,
        "on_exceed": budget.on_exceed,
        "downgrade_model": budget.downgrade_model,
        "alert_threshold": str(budget.alert_threshold),
    }


def _uuid(value):
    import uuid

    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


class BudgetDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Change a budget's limit, currency or behaviour")
    def patch(self, request, org_id, budget_id):
        org, error = _budget_gate(request, self, org_id, "budget.manage")
        if error:
            return error
        budget = get_object_or_404(Budget, pk=budget_id, org=org)
        data = request.data if isinstance(request.data, dict) else {}
        try:
            if "cap_amount" in data or "limit_amount" in data:
                cap = _parse_limit(data)
                if cap != budget.cap_amount:
                    budget.alerted_period = ""
                budget.cap_amount = cap
            if "currency" in data:
                budget.currency = _parse_currency(data, budget.currency)
            if "alert_threshold" in data:
                budget.alerted_period = ""
            _apply_behaviour(budget, data, org)
        except ValueError as exc:
            return _bad(str(exc))
        budget.save()
        audit(request.user, "budget.update", target=budget, payload=_audit_payload(budget), request=request, org=org)
        return Response(_budget_payload(budget))

    @extend_schema(summary="Remove a budget")
    def delete(self, request, org_id, budget_id):
        org, error = _budget_gate(request, self, org_id, "budget.manage")
        if error:
            return error
        budget = get_object_or_404(Budget, pk=budget_id, org=org)
        audit(request.user, "budget.delete", target=budget, payload=_audit_payload(budget), request=request, org=org)
        budget.delete()
        return Response(status=204)


class BudgetStatusView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Read current platform spend against each budget")
    def get(self, request, org_id):
        org, error = _budget_gate(request, self, org_id, "budget.view")
        if error:
            return error
        book = PriceBook()
        rows = list(Budget.objects.filter(org=org).select_related("org"))
        results = []
        for budget in rows:
            spent = budget_spend(budget, book)
            maybe_alert(budget, spent)
            results.append(_budget_payload(budget, spent))
        org_row = next((r for r in results if r["scope_type"] == Budget.SCOPE_ORG), None)
        from telemetry.pricing import month_spend

        return Response(
            {
                "spent": org_row["spent"] if org_row else str(month_spend(org)),
                "cap_amount": org_row["cap_amount"] if org_row else None,
                "currency": org_row["currency"] if org_row else "USD",
                "results": results,
            }
        )


class MyBudgetsView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Budgets that apply to me: my own, and my teams' when I lead them")
    def get(self, request, org_id):
        org, error = _budget_gate(request, self, org_id, "ai.usage.view")
        if error:
            return error
        if can(request.user, "budget.view", org):
            rows = Budget.objects.filter(org=org)
        else:
            led = TeamMembership.objects.filter(
                team__org=org, user=request.user, team_role=TeamMembership.ROLE_LEAD
            ).values_list("team_id", flat=True)
            rows = Budget.objects.filter(org=org, scope_type=Budget.SCOPE_USER, scope_id=request.user.id) | Budget.objects.filter(
                org=org, scope_type=Budget.SCOPE_TEAM, scope_id__in=list(led)
            )
        book = PriceBook()
        return Response([_budget_payload(b, budget_spend(b, book)) for b in rows.select_related("org")])
