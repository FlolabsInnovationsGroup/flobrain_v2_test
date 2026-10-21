import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.mail import send_mail
from django.utils import timezone

from organizations.models import OrgMembership
from organizations.services import audit, sync_user_type
from users.models import User

ACTIVE = OrgMembership.STATUS_ACTIVE


def register_member(org, actor, email: str, *, org_role=OrgMembership.ORG_ROLE_MEMBER, username=""):
    """Q34: attach to the existing users row when the email already exists."""
    user = User.objects.filter(email__iexact=email).first()  # review: a mixed-case stored email is the same person
    created = False
    temp_password = None
    if user is None:
        temp_password = secrets.token_urlsafe(12)
        user = User.objects.create(
            email=email,
            username=username or email.split("@")[0],
            password_hash=make_password(temp_password),
            must_change_password=True,
            temp_password_expires_at=timezone.now()
            + timedelta(hours=settings.FLOBRAIN_V2["TEMP_PASSWORD_LIFETIME_HOURS"]),
        )
        created = True
        base = settings.FRONTEND_BASE_URL.rstrip("/")
        send_mail(
            subject="Your FloBrain workspace invitation",
            message=f"Sign in at {base}/w/signin then set a password at {base}/w/first-login.\nTemporary password: {temp_password}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=True,
        )
    membership, membership_created = OrgMembership.objects.get_or_create(
        org=org,
        user=user,
        defaults={
            "org_role": org_role,
            "employment_status": OrgMembership.STATUS_PENDING,
        },
    )
    sync_user_type(user)
    if actor is not None:
        audit(actor, "member.register", target=membership, org=org, payload={"created_user": created})
    return membership, user, temp_password if created else None


def v2_workspace_signin_allowed(user) -> bool:
    """Pending or fully inactive members cannot use V2 sign-in. Personal users may."""
    memberships = list(OrgMembership.objects.filter(user=user))
    if not memberships:
        return True
    return any(m.employment_status == OrgMembership.STATUS_ACTIVE for m in memberships)


def can_receive_dm(user, org) -> bool:
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    return bool(membership and membership.is_active_member)


def change_member_status(org, actor, user, status: str, reason=""):
    membership = OrgMembership.objects.get(org=org, user=user)
    membership.employment_status = status
    membership.status_changed_at = timezone.now()
    membership.status_changed_by = actor
    membership.status_reason = reason
    membership.save()
    if status in {
        OrgMembership.STATUS_TERMINATED,
        OrgMembership.STATUS_OFFBOARDING,
        OrgMembership.STATUS_PAUSED,
    }:
        user.password_changed_at = timezone.now()
        user.save(update_fields=["password_changed_at"])
    sync_user_type(user)
    audit(actor, "member.status", target=membership, org=org, payload={"status": status})
    return membership
