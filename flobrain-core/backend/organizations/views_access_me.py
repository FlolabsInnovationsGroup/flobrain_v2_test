"""What the signed-in person can do in one org (drives the workspace navigation).

``GET /orgs/{org}/me/access`` → role, teams they lead, org-level permission keys they hold,
effective feature flags, and the demo role when this is a demo user. It only reports;
every endpoint still checks on its own.
"""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from core_v2.views import V2APIView
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization, TeamMembership
from organizations.permissions import IsActiveOrgMember
from organizations.permissions.engine import org_permissions
from organizations.permissions.registry import PERMISSION_CATALOG

# No ``privacy_center`` flag: the privacy page is a right (Decision 44), so nothing switches it off.
KNOWN_FLAGS = (
    "ai_actions", "api_access", "assign_suggestions", "auto_reports", "budgets", "buddies", "byok", "content_studio",
    "live_translation", "memory_search", "realtime", "room_ai", "scheduled_agents", "social_publishing", "voice_video",
    "webhooks", "learning", "commissions", "pulse", "integrations", "meeting_bot", "cockpit", "status_page", "external_agents", "public_portfolio",
)


class MyAccessView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="My role, permissions and feature flags in this org")
    def get(self, request, org_id):
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        membership = OrgMembership.objects.filter(org=org, user=request.user).first()
        leads = list(
            TeamMembership.objects.filter(team__org=org, user=request.user, team_role=TeamMembership.ROLE_LEAD).values_list("team_id", flat=True)
        )
        demo = getattr(request.user, "demo_account", None) if hasattr(request.user, "demo_account") else None
        return Response(
            {
                "org": {"id": str(org.id), "slug": org.slug, "name": org.name, "demo": bool((org.settings or {}).get("demo"))},
                "user_id": str(request.user.id),
                "org_role": membership.org_role if membership else None,
                "is_platform_admin": bool(request.user.is_platform_admin),
                "leads_teams": [str(t) for t in leads],
                "permissions": sorted(org_permissions(request.user, org) & set(PERMISSION_CATALOG)),
                "flags": {k: effective_flag(org, membership, k, default=False) for k in KNOWN_FLAGS},
                "demo_role": demo.role if demo else None,
            }
        )
