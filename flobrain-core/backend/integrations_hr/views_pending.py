"""Pending members (Decision 41): people pushed by the HR webhook or registered without activation.

``GET /orgs/{org}/pending-members`` lists them; ``POST .../{user}/confirm`` (``team_id``) activates
the account and puts the person on that team; ``POST .../{user}/decline`` closes it. Admins act on
anyone; a team lead confirms only into a team they lead, as a plain member.
"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from core_v2.views import V2APIView
from organizations.models import HRApplicant, OrgMembership, Organization, Team, TeamMembership
from organizations.permissions import IsActiveOrgMember, can
from organizations.services import audit
from organizations.services.members import change_member_status


def _org(request, org_id):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    return org


def _led(user, org):
    return set(
        TeamMembership.objects.filter(user=user, team__org=org, team_role=TeamMembership.ROLE_LEAD).values_list("team_id", flat=True)
    )


def _denied():
    return Response({"error": "permission_denied", "details": "Only admins and team leads confirm new members"}, status=403)


def _payload(membership, applicant, show_contact, teams=None):
    user = membership.user
    data = {
        "id": str(user.id),
        "username": user.username,
        "full_name": applicant.full_name if applicant else (user.username or ""),
        "source": applicant.source if applicant else "registered",
        "reference": applicant.reference if applicant else "",
        "created_at": (applicant.created_at if applicant else membership.created_at).isoformat(),
        "teams": teams.get(user.id, [])
        if teams is not None
        else [
            {"id": str(t.team_id), "name": t.team.name}
            for t in TeamMembership.objects.filter(user=user, team__org=membership.org).select_related("team")
        ],
    }
    if show_contact:
        data["email"] = user.email
    return data


class PendingMemberListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="People waiting for a lead or admin to confirm them")
    def get(self, request, org_id):
        org = _org(request, org_id)
        if not can(request.user, "org.members.manage", org) and not _led(request.user, org):
            return _denied()
        rows = list(
            OrgMembership.objects.filter(org=org, employment_status=OrgMembership.STATUS_PENDING)
            .select_related("user", "org")
            .order_by("-created_at")[:200]
        )
        applicants = {}
        for a in HRApplicant.objects.filter(org=org, membership_id__in=[m.id for m in rows]).order_by("created_at"):
            applicants[a.membership_id] = a  # the latest push wins
        show_contact = can(request.user, "org.members.view_contact", org)
        teams = {}
        for t in TeamMembership.objects.filter(team__org=org, user_id__in=[m.user_id for m in rows]).select_related("team"):
            teams.setdefault(t.user_id, []).append({"id": str(t.team_id), "name": t.team.name})
        return Response([_payload(m, applicants.get(m.id), show_contact, teams) for m in rows])


class PendingMemberDecideView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Confirm (with a team) or decline a pending member")
    def post(self, request, org_id, user_id, decision):
        org = _org(request, org_id)
        manager = can(request.user, "org.members.manage", org)
        led = _led(request.user, org)
        if not manager and not led:
            return _denied()
        if decision not in {"confirm", "decline"}:
            return Response({"error": "not_found", "details": "Use confirm or decline"}, status=404)
        membership = (
            OrgMembership.objects.filter(org=org, user_id=user_id, employment_status=OrgMembership.STATUS_PENDING)
            .select_related("user")
            .first()
        )
        if membership is None:
            return Response({"error": "not_found", "details": "No pending member with this id"}, status=404)
        body = request.data if isinstance(request.data, dict) else {}
        if decision == "decline":
            if not manager:
                return Response({"error": "permission_denied", "details": "Only admins decline applicants"}, status=403)
            reason = str(body.get("reason") or "Declined")[:500]
            change_member_status(org, request.user, membership.user, OrgMembership.STATUS_TERMINATED, reason=reason)
            audit(request.user, "member.decline", target=membership, org=org, request=request, payload={"user": str(user_id)})
            return Response({"id": str(user_id), "employment_status": OrgMembership.STATUS_TERMINATED})

        team = Team.objects.filter(pk=body.get("team_id"), org=org, is_active=True).first() if _is_uuid(body.get("team_id")) else None
        if team is None:
            return Response({"error": "invalid", "details": {"team_id": "Pick an active team for this person"}}, status=400)
        if not manager and team.id not in led:
            return Response({"error": "permission_denied", "details": "You can confirm people only into a team you lead"}, status=403)
        with transaction.atomic():
            TeamMembership.objects.get_or_create(team=team, user=membership.user, defaults={"team_role": TeamMembership.ROLE_MEMBER})
            change_member_status(org, request.user, membership.user, OrgMembership.STATUS_ACTIVE, reason="Confirmed")
            sent = _send_welcome(membership.user, org)
        audit(
            request.user, "member.confirm", target=membership, org=org, request=request,
            payload={"user": str(user_id), "team": str(team.id), "welcome_sent": sent},
        )
        return Response({"id": str(user_id), "employment_status": OrgMembership.STATUS_ACTIVE, "team": {"id": str(team.id), "name": team.name}})


def _is_uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


def _send_welcome(user, org) -> bool:
    """A fresh temporary password, because the one sent at intake may have expired (72 h)."""
    if getattr(user, "provider", "") == "demo" or not user.must_change_password:
        return False
    temp = secrets.token_urlsafe(12)
    user.password_hash = make_password(temp)
    user.temp_password_expires_at = timezone.now() + timedelta(hours=settings.FLOBRAIN_V2["TEMP_PASSWORD_LIFETIME_HOURS"])
    user.save(update_fields=["password_hash", "temp_password_expires_at"])
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    send_mail(
        subject=f"You're in: {org.name} on FloBrain",
        message=(
            f"Your FloBrain account for {org.name} is active.\n"
            f"Sign in at {base}/w/signin, then set your password and phone number.\n"
            f"Temporary password: {temp}"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=True,
    )
    return True
