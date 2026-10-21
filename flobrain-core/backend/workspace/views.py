"""Cockpit layout and presence (Phase 10).

``GET/PUT /me/cockpit-layout`` and ``PATCH /orgs/{org}/me/presence``.
"""

import re

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core_v2.views import V2APIView
from organizations.models import OrgMembership, Organization
from organizations.permissions import IsActiveOrgMember
from workspace.models import CockpitLayout

WIDGETS = ("impact", "progress", "tasks", "buddies", "commission", "approvals", "announcements")
ROOM_TABS = ("chat", "ai", "tasks", "docs", "calendar", "recordings", "report", "team")
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
DEFAULT_LAYOUT = {
    "panels": {"rooms": True, "video": False, "compact": False, "right_rail": True},
    "widgets": ["impact", "progress", "tasks", "approvals", "buddies"],
    "default_room_tab": "chat",
    "accent": "",
}


def clean_layout(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("layout must be an object")
    out = {**DEFAULT_LAYOUT}
    panels = raw.get("panels", {})
    if not isinstance(panels, dict) or not set(panels) <= set(DEFAULT_LAYOUT["panels"]):
        raise ValueError("panels may only set rooms, video, compact and right_rail")
    if not all(isinstance(v, bool) for v in panels.values()):
        raise ValueError("panel values must be true or false")
    out["panels"] = {**DEFAULT_LAYOUT["panels"], **panels}
    widgets = raw.get("widgets", DEFAULT_LAYOUT["widgets"])
    if not isinstance(widgets, list) or not all(isinstance(w, str) and w in WIDGETS for w in widgets):
        raise ValueError(f"widgets must come from {', '.join(WIDGETS)}")
    out["widgets"] = list(dict.fromkeys(widgets))
    tab = raw.get("default_room_tab", "chat")
    if tab not in ROOM_TABS:
        raise ValueError("unknown default_room_tab")
    out["default_room_tab"] = tab
    accent = raw.get("accent", "") or ""
    if accent and not (isinstance(accent, str) and COLOR.fullmatch(accent)):
        raise ValueError("accent must be a colour like #7c3aed")
    out["accent"] = accent
    return out


def _payload(row):
    return {"mode": row.mode, "layout": {**DEFAULT_LAYOUT, **(row.layout or {})}, "low_bandwidth": row.low_bandwidth, "updated_at": row.updated_at.isoformat()}


class CockpitLayoutView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="My cockpit layout")
    def get(self, request):
        row = CockpitLayout.objects.filter(user=request.user).first() or CockpitLayout(user=request.user)
        return Response(_payload(row))

    @extend_schema(summary="Save my cockpit layout")
    def put(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        row = CockpitLayout.objects.filter(user=request.user).first() or CockpitLayout(user=request.user)
        if "mode" in data:
            if data["mode"] not in CockpitLayout.MODES:
                return Response({"error": "invalid", "details": "mode must be default, focus or custom"}, status=400)
            row.mode = data["mode"]
        if "layout" in data:
            try:
                row.layout = clean_layout(data["layout"])
            except ValueError as exc:
                return Response({"error": "invalid", "details": str(exc)}, status=400)
        if "low_bandwidth" in data:
            if not isinstance(data["low_bandwidth"], bool):
                return Response({"error": "invalid", "details": "low_bandwidth must be true or false"}, status=400)
            row.low_bandwidth = data["low_bandwidth"]
        row.updated_at = timezone.now()
        row.save()
        return Response(_payload(row))


class PresenceView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Set my presence in this org")
    def patch(self, request, org_id):
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        data = request.data if isinstance(request.data, dict) else {}
        value = data.get("presence")
        allowed = {choice for choice, _ in OrgMembership.PRESENCE_CHOICES}
        if value not in allowed:
            return Response({"error": "invalid", "details": f"presence must be one of {', '.join(sorted(allowed))}"}, status=400)
        OrgMembership.objects.filter(org=org, user=request.user).update(presence=value, presence_updated_at=timezone.now())
        return Response({"presence": value})
