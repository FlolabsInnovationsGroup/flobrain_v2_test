"""Product analytics and in-app feedback (Phase 0).

Events: allowlisted names and property keys only, never content; nothing is stored when the person
said no to product analytics. Dashboards show aggregates where at least ``MIN_USERS`` people are in
a cell, and leave out people who chose ``analytics_personal_only``.

Feedback: anyone in the org reports a problem or an idea and sees their own reports; owners and
admins read the inbox and move items through new, triaged and closed.
"""

from datetime import timedelta
from urllib.parse import urlparse

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from core_v2.pagination import V2PageNumberPagination
from core_v2.views import V2APIView
from organizations.models import OrgMembership, Organization
from organizations.permissions import HasPerm, IsActiveOrgMember
from organizations.services import audit
from telemetry.models import FeedbackItem, ProductEvent

ALLOWED_EVENT_NAMES = frozenset({"page.viewed", "feature.used", "funnel.step"})
ALLOWED_PROPERTIES = frozenset({"page", "feature", "step", "source"})
MAX_BATCH = 20
MIN_USERS = 5
FEEDBACK_STATUSES = {c[0] for c in FeedbackItem.STATUS_CHOICES}
FEEDBACK_KINDS = {c[0] for c in FeedbackItem.KIND_CHOICES}


def _org(org_id):
    return get_object_or_404(Organization, pk=org_id, is_active=True)


def _is_org_admin(user, org) -> bool:
    if getattr(user, "is_platform_admin", False):
        return True
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    return bool(
        membership
        and membership.is_active_member
        and membership.org_role in {OrgMembership.ORG_ROLE_OWNER, OrgMembership.ORG_ROLE_ADMIN}
    )


def _admin_only():
    return Response({"error": "permission_denied", "details": "Admin only"}, status=status.HTTP_403_FORBIDDEN)


def _clean_page(value: str) -> str:
    raw = (value or "").split("?", 1)[0].split("#", 1)[0]
    parsed = urlparse(raw)
    return (parsed.path or raw)[:255]


def _clean_event(raw):
    """(name, properties) or raises ValueError with the reason."""
    if not isinstance(raw, dict):
        raise ValueError("Each event must be an object")
    name = str(raw.get("name") or "").strip()
    if name not in ALLOWED_EVENT_NAMES:
        raise ValueError("Event name is not allowlisted")
    props = raw.get("properties") or {}
    if not isinstance(props, dict):
        raise ValueError("properties must be an object")
    clean = {k: str(v)[:120] for k, v in props.items() if k in ALLOWED_PROPERTIES and isinstance(v, (str, int, float))}
    if "page" in clean:
        clean["page"] = _clean_page(clean["page"])
    return name, clean


class ProductEventCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("org.view").has_permission(request, self)
        data = request.data if isinstance(request.data, dict) else {}
        batch = "events" in data
        raw_events = data.get("events") if batch else [data]
        if not isinstance(raw_events, list) or not raw_events or len(raw_events) > MAX_BATCH:
            return Response(
                {"error": "invalid_events", "details": f"events must be a list of 1 to {MAX_BATCH} events"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            cleaned = [_clean_event(e) for e in raw_events]
        except ValueError as exc:
            code = "invalid_event" if "allowlisted" in str(exc) else "invalid_properties"
            return Response({"error": code, "details": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        from privacy.models import PrivacySettings

        settings_row = PrivacySettings.objects.filter(org=org, user=request.user).first()
        if settings_row and (settings_row.consents or {}).get("product_analytics") is False:
            return Response({"ok": True, "recorded": False}, status=status.HTTP_202_ACCEPTED)  # they said no
        events = ProductEvent.objects.bulk_create(
            [ProductEvent(org=org, user=request.user, name=name, properties=props) for name, props in cleaned]
        )
        if batch:
            return Response({"ok": True, "recorded": len(events)}, status=status.HTTP_201_CREATED)
        return Response({"id": str(events[0].id), "ok": True}, status=status.HTTP_201_CREATED)


def _feedback_row(item, with_reporter=False):
    data = {
        "id": str(item.id),
        "kind": item.kind,
        "page": item.page,
        "text": item.text,
        "browser": item.browser,
        "screenshot_note": item.screenshot_note,
        "status": item.status,
        "created_at": item.created_at.isoformat(),
    }
    if with_reporter:
        data["user"] = {"id": str(item.user_id), "username": item.user.username or ""} if item.user_id else None
    return data


class FeedbackCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        """My own reports, newest first."""
        org = _org(org_id)
        request.org = org
        HasPerm("org.view").has_permission(request, self)
        qs = FeedbackItem.objects.filter(org=org, user=request.user).order_by("-created_at")
        paginator = V2PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([_feedback_row(i) for i in page])

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("org.view").has_permission(request, self)
        data = request.data if isinstance(request.data, dict) else {}
        kind = data.get("kind")
        text = str(data.get("text") or "").strip()
        page = _clean_page(str(data.get("page") or ""))
        if kind not in FEEDBACK_KINDS or not text:
            return Response(
                {"error": "invalid_feedback", "details": "kind and text are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(text) > 4000:
            return Response({"error": "invalid_feedback", "details": "Keep it under 4000 characters"}, status=400)
        note = str(data.get("screenshot_note") or "").strip()
        if len(note) > 2000:
            return Response({"error": "invalid_feedback", "details": "Keep the screen description under 2000 characters"}, status=400)
        item = FeedbackItem.objects.create(
            org=org,
            user=request.user,
            page=page,
            kind=kind,
            text=text,
            screenshot_file=str(data.get("screenshot_file") or "")[:500],
            screenshot_note=note,
            browser=str(data.get("browser") or "")[:255],
        )
        return Response({"id": str(item.id), "ok": True}, status=status.HTTP_201_CREATED)


class AdminFeedbackListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        if not _is_org_admin(request.user, org):
            return _admin_only()
        qs = FeedbackItem.objects.filter(org=org).select_related("user").order_by("-created_at")
        status_filter = request.query_params.get("status")
        if status_filter:
            if status_filter not in FEEDBACK_STATUSES:
                return Response({"error": "invalid", "details": "status must be new, triaged or closed"}, status=400)
            qs = qs.filter(status=status_filter)
        kind = request.query_params.get("kind")
        if kind:
            if kind not in FEEDBACK_KINDS:
                return Response({"error": "invalid", "details": "kind must be bug, idea or question"}, status=400)
            qs = qs.filter(kind=kind)
        paginator = V2PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([_feedback_row(i, with_reporter=True) for i in page])


class AdminFeedbackDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def patch(self, request, org_id, item_id):
        org = _org(org_id)
        request.org = org
        if not _is_org_admin(request.user, org):
            return _admin_only()
        item = get_object_or_404(FeedbackItem.objects.select_related("user"), pk=item_id, org=org)
        value = (request.data if isinstance(request.data, dict) else {}).get("status")
        if value not in FEEDBACK_STATUSES:
            return Response({"error": "invalid", "details": "status must be new, triaged or closed"}, status=400)
        if value != item.status:
            before = item.status
            item.status = value
            item.save(update_fields=["status"])
            audit(request.user, "feedback.status", target=item, org=org, request=request, payload={"from": before, "to": value})
        return Response(_feedback_row(item, with_reporter=True))


class AdminAnalyticsView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        if not _is_org_admin(request.user, org):
            return _admin_only()
        try:
            days = int(request.query_params.get("days") or 30)
        except ValueError:
            days = 0
        if not 1 <= days <= 365:
            return Response({"error": "invalid", "details": "days must be between 1 and 365"}, status=400)
        from privacy.models import PrivacySettings

        since = timezone.now() - timedelta(days=days)
        personal = PrivacySettings.objects.filter(org=org, analytics_personal_only=True).values_list("user_id", flat=True)
        base = ProductEvent.objects.filter(org=org, created_at__gte=since).exclude(user_id__in=list(personal))

        def cells(qs, field, label):
            rows = (
                qs.filter(**{f"properties__{field}__isnull": False})
                .values(f"properties__{field}")
                .annotate(events=Count("id"), users=Count("user", distinct=True))
                .order_by("-events")
            )
            shown, hidden = [], 0
            for row in rows:
                if row["users"] >= MIN_USERS:
                    shown.append({label: row[f"properties__{field}"], "events": row["events"], "users": row["users"]})
                else:
                    hidden += 1
            return shown[:50], hidden

        page_views = base.filter(name="page.viewed")
        pages, hidden_pages = cells(page_views, "page", "page")
        features, hidden_features = cells(base.filter(name="feature.used"), "feature", "feature")
        by_day, hidden_days = [], 0
        for row in (
            page_views.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(events=Count("id"), users=Count("user", distinct=True))
            .order_by("day")
        ):
            if row["users"] >= MIN_USERS:
                by_day.append({"day": row["day"].isoformat(), "events": row["events"], "users": row["users"]})
            else:
                hidden_days += 1
        total_users = base.values("user").distinct().count()
        return Response(
            {
                "days": days,
                "min_users": MIN_USERS,
                "event_names": sorted(set(base.values_list("name", flat=True).distinct())),
                "count": base.count(),
                "active_users": total_users if total_users >= MIN_USERS else None,
                "pages": pages,
                "features": features,
                "by_day": by_day,
                "hidden": {"pages": hidden_pages, "features": hidden_features, "days": hidden_days},
            }
        )
