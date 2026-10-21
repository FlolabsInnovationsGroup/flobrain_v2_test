"""People and access demo data: phone numbers, HR applicants waiting for confirmation, grants
(one about to expire), permission requests, audit history, feedback reports and page-view events.
Every row is in the demo org; new people use the demo domain and provider ``demo`` so ``wipe()``
removes them."""

from datetime import timedelta

from django.contrib.auth.hashers import make_password

PHONES = {
    "owner": "+201000000101",
    "admin": "+201000000102",
    "lead": "+201000000103",
    "member": "+201000000104",
    "designer": "+201000000105",
}
APPLICANTS = [
    ("applicant1", "Hana Farouk", "n8n-2026-0412", 1),
    ("applicant2", "Karim Said", "n8n-2026-0415", 3),
]
PAGES = ["/home", "/tasks", "/rooms", "/time", "/directory", "/calendar"]


def seed(org, users, now):
    from demo.seed import email_for
    from organizations.models import (
        AuditEvent,
        HRApplicant,
        OrgMembership,
        PermissionGrant,
        PermissionRequest,
        Team,
    )
    from telemetry.models import FeedbackItem, ProductEvent
    from users.models import User

    for key, phone in PHONES.items():
        if key in users:
            users[key].phone = phone
            users[key].timezone = "Africa/Cairo"
            users[key].about_me = users[key].about_me or "Demo profile."
            users[key].save(update_fields=["phone", "timezone", "about_me"])

    owner, admin, lead, member, designer = (users[k] for k in ("owner", "admin", "lead", "member", "designer"))
    design = Team.objects.filter(org=org, name="Design").first()

    def event(actor, action, target_type="", target_id="", payload=None, days_ago=0.0):
        row = AuditEvent.objects.create(
            org=org, actor=actor, action=action, target_type=target_type, target_id=str(target_id), payload={"demo": True, **(payload or {})}
        )
        AuditEvent.objects.filter(pk=row.pk).update(created_at=now - timedelta(days=days_ago))

    # HR intake (Decision 41): pushed by n8n, waiting for a lead or admin to pick their team.
    for key, name, reference, days_ago in APPLICANTS:
        user = User.objects.create(
            email=email_for(key), username=name, password_hash=make_password(None), provider="demo", must_change_password=True
        )
        membership = OrgMembership.objects.create(org=org, user=user, employment_status=OrgMembership.STATUS_PENDING)
        applicant = HRApplicant.objects.create(
            org=org, email=user.email, full_name=f"{name} (Demo)", source="hr_webhook", reference=reference,
            payload={"keys": ["email", "full_name", "org_slug", "reference"]}, membership=membership,
        )
        HRApplicant.objects.filter(pk=applicant.pk).update(created_at=now - timedelta(days=days_ago))

    # Grants: one ends tomorrow, one lasts a week, one has no end.
    expiring = PermissionGrant.objects.create(
        org=org, grantee=lead, perm_key="audit.view", granted_by=admin, expires_at=now + timedelta(days=1)
    )
    event(admin, "perm.grant", "PermissionGrant", expiring.id, {"perm_key": "audit.view", "grantee": str(lead.id)}, days_ago=6)
    if design is not None:
        week = PermissionGrant.objects.create(
            org=org, grantee=member, perm_key="team.manage", scope_type="team", scope_id=design.id,
            granted_by=admin, expires_at=now + timedelta(days=7),
        )
        event(admin, "perm.grant", "PermissionGrant", week.id, {"perm_key": "team.manage", "grantee": str(member.id), "scope_type": "team"}, days_ago=0.2)
    lasting = PermissionGrant.objects.create(org=org, grantee=designer, perm_key="content.manage", granted_by=owner)
    event(owner, "perm.grant", "PermissionGrant", lasting.id, {"perm_key": "content.manage", "grantee": str(designer.id)}, days_ago=12)

    # Permission requests (Decision 29): two waiting, one already turned down.
    waiting = PermissionRequest.objects.create(
        org=org, requester=member, perm_key="audit.view", reason="Demo: I want to see who moved the release date."
    )
    event(member, "perm.request.create", "PermissionRequest", waiting.id, {"perm_key": "audit.view"}, days_ago=0.5)
    budget = PermissionRequest.objects.create(
        org=org, requester=designer, perm_key="budget.view", reason="Demo: planning how many video renders we can afford."
    )
    event(designer, "perm.request.create", "PermissionRequest", budget.id, {"perm_key": "budget.view"}, days_ago=1)
    rejected = PermissionRequest.objects.create(
        org=org, requester=member, perm_key="hr.view", reason="Demo: looking for the onboarding checklist.",
        status=PermissionRequest.STATUS_REJECTED, decided_by=admin, decided_at=now - timedelta(days=3),
    )
    event(admin, "perm.request.reject", "PermissionRequest", rejected.id, {"perm_key": "hr.view"}, days_ago=3)

    # A little history for the audit viewer.
    event(owner, "team.create", "Team", design.id if design else "", {"name": "Design"}, days_ago=20)
    event(admin, "member.register", "OrgMembership", "", {"created_user": True}, days_ago=18)
    event(lead, "member.status", "OrgMembership", "", {"status": "active"}, days_ago=17)
    event(admin, "member.role", "OrgMembership", "", {"from": "member", "to": "admin"}, days_ago=15)

    # In-app feedback (Phase 0).
    for who, kind, page, text, note, status, days_ago in (
        (member, "bug", "/w/demo/tasks", "Demo: dragging a card to Done sometimes snaps it back.", "The card returns to In Progress after a second.", "new", 0.3),
        (designer, "idea", "/w/demo/rooms", "Demo: let me pin a doc to the top of a room.", "", "triaged", 2),
        (lead, "question", "/w/demo/time", "Demo: do weekly targets count onboarding hours?", "", "closed", 5),
    ):
        item = FeedbackItem.objects.create(
            org=org, user=who, page=page, kind=kind, text=text, screenshot_note=note, browser="Demo browser", status=status
        )
        FeedbackItem.objects.filter(pk=item.pk).update(created_at=now - timedelta(days=days_ago))

    # Page views from the five demo people, so the analytics view has cells above its 5-person floor.
    people = [owner, admin, lead, member, designer]
    rows = []
    for day in range(10):
        for i, who in enumerate(people):
            for page in PAGES[: 3 + (day + i) % 4]:
                rows.append(
                    ProductEvent(org=org, user=who, name="page.viewed", properties={"page": page, "source": "demo"},
                                 created_at=now - timedelta(days=day, hours=i))
                )
    for who in people:
        rows.append(ProductEvent(org=org, user=who, name="feature.used", properties={"feature": "timer", "source": "demo"}, created_at=now - timedelta(days=1)))
    ProductEvent.objects.bulk_create(rows)
