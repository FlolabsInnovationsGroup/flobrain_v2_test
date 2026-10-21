"""Platform console (Phase 17e). Platform admins only, every change audited in the org.

- ``GET /platform/orgs?q=``: orgs with member count, plan and flags
- ``GET/PUT /platform/orgs/{org}/flags``: org feature flags (booleans)
- ``GET/POST /platform/impersonations``: start a read-only session (reason, 5..60 minutes)
- ``POST /platform/impersonations/{id}/end``
Customer side (``audit.view``): ``GET /orgs/{org}/impersonations`` and
``POST /orgs/{org}/impersonations/{id}/end`` so the org can see and stop support access.
"""

import re
import uuid
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from console import impersonation
from console.models import ImpersonationSession
from core_v2.views import V2APIView
from organizations.models import OrgMembership, Organization
from organizations.permissions import HasPerm, IsActiveOrgMember
from organizations.services.core import audit

FLAG_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,48}[a-z0-9]")
EMAIL_RE = re.compile(r"[^@\s]{1,64}@[^@\s]{1,255}\.[A-Za-z]{2,}")
# The demo org, and every static page under /w/ (an org there could never be opened).
RESERVED_SLUGS = {"demo", "admin", "api", "platform", "www", "app", "w", "signin", "sso", "first-login", "reset-password", "verify", "p"}


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def _denied():
    return Response({"error": "permission_denied", "details": "Platform admins only"}, status=403)


def _is_admin(request):
    user = request.user
    # An impersonation token is never a platform admin, even if the person behind it is.
    return bool(
        user and user.is_authenticated and getattr(user, "is_platform_admin", False)
        and not (isinstance(request.auth, dict) and request.auth.get("impersonation"))
    )


def session_payload(s, with_reason=True):
    data = {
        "id": str(s.id),
        "org": str(s.org_id),
        "user": {"id": str(s.user_id), "email": s.user.email},
        "admin": {"id": str(s.admin_id), "email": s.admin.email},
        "created_at": s.created_at.isoformat(),
        "expires_at": s.expires_at.isoformat(),
        "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        "live": s.is_live,
    }
    if with_reason:
        data["reason"] = s.reason
    return data


class PlatformView(V2APIView):
    permission_classes = []


class PlatformOrgListView(PlatformView):
    @extend_schema(summary="Orgs (platform admins)")
    def get(self, request):
        if not _is_admin(request):
            return _denied()
        q = (request.query_params.get("q") or "").strip()[:100]
        orgs = Organization.objects.all()
        if q:
            orgs = orgs.filter(Q(name__icontains=q) | Q(slug__icontains=q))
        orgs = orgs.annotate(members=Count("memberships", filter=Q(memberships__employment_status="active"))).order_by("name")[:100]
        from billing_v2.models import Subscription

        plans = {
            str(s.org_id): {"plan": s.plan.code, "status": s.status}
            for s in Subscription.objects.filter(org__in=[o.id for o in orgs]).select_related("plan")
        }
        return Response(
            [
                {
                    "id": str(o.id),
                    "name": o.name,
                    "slug": o.slug,
                    "is_active": o.is_active,
                    "active_members": o.members,
                    "subscription": plans.get(str(o.id)),
                    "flags": (o.settings or {}).get("flags", {}),
                }
                for o in orgs
            ]
        )

    @extend_schema(summary="Onboard an org: create it and invite its owner (platform admins)")
    def post(self, request):
        if not _is_admin(request):
            return _denied()
        body = _body(request)
        name = body.get("name")
        slug = body.get("slug")
        email = body.get("owner_email")
        errors = {}
        if not isinstance(name, str) or not 2 <= len(name.strip()) <= 200:
            errors["name"] = "2 to 200 characters"
        if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug) or slug in RESERVED_SLUGS:
            errors["slug"] = "3 to 50 lowercase letters, digits and dashes; not a reserved word"
        if not isinstance(email, str) or not EMAIL_RE.fullmatch(email.strip()):
            errors["owner_email"] = "a valid email"
        if errors:
            return Response({"error": "invalid", "details": errors}, status=400)
        if Organization.objects.filter(slug=slug).exists():
            return Response({"error": "conflict", "details": "That address is taken"}, status=409)
        from django.conf import settings
        from django.core.mail import send_mail
        from django.db import IntegrityError

        from organizations.services.members import register_member

        try:
            with transaction.atomic():
                org = Organization.objects.create(name=name.strip(), slug=slug)
                membership, user, temp = register_member(
                    org, request.user, email.strip().lower(), org_role=OrgMembership.ORG_ROLE_OWNER, username=str(body.get("owner_username") or "")[:150]
                )
                # Review 15-16: a pending owner can't sign in and nobody else could activate them.
                membership.employment_status = OrgMembership.STATUS_ACTIVE
                membership.status_changed_at, membership.status_changed_by = timezone.now(), request.user
                membership.save()
                audit(request.user, "platform.org.create", target=org, payload={"owner": email.strip().lower()}, request=request, org=org)
        except IntegrityError:
            return Response({"error": "conflict", "details": "That address is taken"}, status=409)
        if temp is None:  # an existing account: no invitation email went out, so tell them
            base = settings.FRONTEND_BASE_URL.rstrip("/")
            send_mail(
                subject=f"You now own {org.name} on FloBrain",
                message=f"Open your new workspace at {base}/w/{org.slug}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,
            )
        return Response({"id": str(org.id), "name": org.name, "slug": org.slug, "owner_membership": str(membership.id)}, status=201)


class PlatformOrgFlagsView(PlatformView):
    @extend_schema(summary="Org flags (platform admins)")
    def get(self, request, org_id):
        if not _is_admin(request):
            return _denied()
        org = get_object_or_404(Organization, pk=org_id)
        return Response({"flags": (org.settings or {}).get("flags", {})})

    @extend_schema(summary="Set org flags (platform admins, audited)")
    def put(self, request, org_id):
        if not _is_admin(request):
            return _denied()
        changes = _body(request).get("flags")
        if not isinstance(changes, dict) or not changes or len(changes) > 50:
            return Response({"error": "invalid", "details": "flags must be an object of booleans"}, status=400)
        for key, value in changes.items():
            if not FLAG_RE.match(str(key)) or not isinstance(value, bool):
                return Response({"error": "invalid", "details": f"flag {key!s:.40} must be a boolean"}, status=400)
        with transaction.atomic():
            org = Organization.objects.select_for_update().get(pk=get_object_or_404(Organization, pk=org_id).pk)
            settings = dict(org.settings or {})
            flags = dict(settings.get("flags") or {})
            before = {k: flags.get(k) for k in changes}
            flags.update(changes)
            settings["flags"] = flags
            org.settings = settings
            org.save(update_fields=["settings"])
            audit(request.user, "platform.flags.update", target=org, payload={"before": before, "after": changes}, request=request, org=org)
        return Response({"flags": flags})


class PlatformImpersonationView(PlatformView):
    @extend_schema(summary="Recent impersonation sessions (platform admins)")
    def get(self, request):
        if not _is_admin(request):
            return _denied()
        sessions = ImpersonationSession.objects.select_related("user", "admin")[:100]
        return Response([session_payload(s) for s in sessions])

    @extend_schema(summary="Start a read-only impersonation session (platform admins, audited, visible to the org)")
    def post(self, request):
        if not _is_admin(request):
            return _denied()
        data = _body(request)
        reason = str(data.get("reason") or "").strip()
        if len(reason) < 10 or len(reason) > 1000:
            return Response({"error": "invalid", "details": "a reason of 10 to 1000 characters is required"}, status=400)
        try:
            minutes = int(data.get("minutes") or 15)
            org_id, user_id = uuid.UUID(str(data.get("org"))), uuid.UUID(str(data.get("user")))
        except (TypeError, ValueError):
            return Response({"error": "invalid", "details": "org, user and minutes are required"}, status=400)
        if not 5 <= minutes <= impersonation.MAX_MINUTES:
            return Response({"error": "invalid", "details": f"minutes must be 5..{impersonation.MAX_MINUTES}"}, status=400)
        membership = OrgMembership.objects.filter(org_id=org_id, user_id=user_id).select_related("org", "user").first()
        if not membership or not membership.is_active_member or not membership.org.is_active:
            return Response({"error": "not_found", "details": "No active member with that id in that org"}, status=404)
        if membership.user.is_platform_admin or membership.user_id == request.user.id:
            return Response({"error": "invalid", "details": "Platform admins cannot be impersonated"}, status=400)
        org, target = membership.org, membership.user
        session = ImpersonationSession.objects.create(
            admin=request.user, org=org, user=target, reason=reason, expires_at=timezone.now() + timedelta(minutes=minutes)
        )
        audit(target, "impersonation.start", target=session, payload={"reason": reason, "minutes": minutes}, request=request, org=org, impersonator=request.user)
        _notify(session)
        return Response({**session_payload(session), "token": impersonation.make_token(session)}, status=201)


def _notify(session):
    """The person viewed and the org's owners and admins see it in their notifications."""
    from notifications.models import Notification

    watchers = set(
        OrgMembership.objects.filter(
            org=session.org,
            employment_status="active",
            org_role__in=[OrgMembership.ORG_ROLE_OWNER, OrgMembership.ORG_ROLE_ADMIN],
        ).values_list("user_id", flat=True)
    ) | {session.user_id}
    payload = {
        "session": str(session.id),
        "user": session.user.email,
        "admin": session.admin.email,
        "reason": session.reason[:300],
        "expires_at": session.expires_at.isoformat(),
    }
    Notification.objects.bulk_create(
        [Notification(org=session.org, user_id=uid, kind="impersonation.started", payload=payload) for uid in watchers]
    )


class PlatformImpersonationEndView(PlatformView):
    @extend_schema(summary="End an impersonation session (platform admins)")
    def post(self, request, session_id):
        if not _is_admin(request):
            return _denied()
        session = get_object_or_404(ImpersonationSession, pk=session_id)
        if impersonation.end(session, request.user):
            audit(session.user, "impersonation.end", target=session, payload={"by": "platform"}, request=request, org=session.org, impersonator=session.admin)
        return Response(status=204)


class OrgImpersonationListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Support sessions on this org (audit.view)")
    def get(self, request, org_id):
        org = get_object_or_404(Organization, pk=org_id)
        request.org = org
        HasPerm("audit.view").has_permission(request, self)
        sessions = ImpersonationSession.objects.filter(org=org).select_related("user", "admin")[:100]
        return Response([session_payload(s) for s in sessions])


class OrgImpersonationEndView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Stop a support session on this org (audit.view)")
    def post(self, request, org_id, session_id):
        org = get_object_or_404(Organization, pk=org_id)
        request.org = org
        HasPerm("audit.view").has_permission(request, self)
        session = get_object_or_404(ImpersonationSession, pk=session_id, org=org)
        if impersonation.end(session, request.user):
            audit(request.user, "impersonation.end", target=session, payload={"by": "org"}, request=request, org=org)
        return Response(status=204)
