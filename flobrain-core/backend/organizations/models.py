import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    settings = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organizations"

    def __str__(self) -> str:
        return self.name


class OrgMembership(models.Model):
    ORG_ROLE_OWNER = "owner"
    ORG_ROLE_ADMIN = "admin"
    ORG_ROLE_MEMBER = "member"
    ORG_ROLE_CHOICES = [
        (ORG_ROLE_OWNER, "Owner"),
        (ORG_ROLE_ADMIN, "Admin"),
        (ORG_ROLE_MEMBER, "Member"),
    ]
    STATUS_PENDING = "pending"
    STATUS_ACTIVE = "active"
    STATUS_PAUSED = "paused"
    STATUS_GRADUATED = "graduated"
    STATUS_TERMINATED = "terminated"
    STATUS_OFFBOARDING = "offboarding"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_GRADUATED, "Graduated"),
        (STATUS_TERMINATED, "Terminated"),
        (STATUS_OFFBOARDING, "Offboarding"),
    ]
    PRESENCE_ONLINE = "online"
    PRESENCE_AWAY = "away"
    PRESENCE_ON_LEAVE = "on_leave"
    PRESENCE_OFFLINE = "offline"
    PRESENCE_CHOICES = [
        (PRESENCE_ONLINE, "Online"),
        (PRESENCE_AWAY, "Away"),
        (PRESENCE_ON_LEAVE, "On leave"),
        (PRESENCE_OFFLINE, "Offline"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="org_memberships")
    org_role = models.CharField(max_length=16, choices=ORG_ROLE_CHOICES, default=ORG_ROLE_MEMBER)
    employment_status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    status_changed_at = models.DateTimeField(blank=True, null=True)
    status_changed_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="membership_status_changes",
    )
    status_reason = models.TextField(blank=True, null=True)
    internship_tier = models.PositiveSmallIntegerField(blank=True, null=True)
    presence = models.CharField(max_length=16, choices=PRESENCE_CHOICES, default=PRESENCE_OFFLINE)
    presence_updated_at = models.DateTimeField(blank=True, null=True)
    notion_member_id = models.CharField(max_length=64, blank=True, null=True)
    feature_flags = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "org_memberships"
        constraints = [
            models.UniqueConstraint(fields=["org", "user"], name="unique_org_membership"),
        ]

    @property
    def is_active_member(self) -> bool:
        return self.employment_status == self.STATUS_ACTIVE


class Team(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "org_teams"
        constraints = [
            models.UniqueConstraint(fields=["org", "name"], name="unique_team_name_per_org"),
        ]


class TeamMembership(models.Model):
    ROLE_LEAD = "lead"
    ROLE_MEMBER = "member"
    ROLE_CHOICES = [(ROLE_LEAD, "Lead"), (ROLE_MEMBER, "Member")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="team_memberships")
    team_role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    weekly_target_hours = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    weekly_task_target = models.PositiveIntegerField(blank=True, null=True)
    joined_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "team_memberships"
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="unique_team_membership"),
        ]


class Project(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_PAUSED = "paused"
    STATUS_DONE = "done"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_DONE, "Done"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="projects")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    lead = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_projects",
    )
    teams = models.ManyToManyField(Team, blank=True, related_name="projects")
    starts_on = models.DateField(blank=True, null=True)
    due_on = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "org_projects"


class ProjectMembership(models.Model):
    SOURCE_TEAM = "team"
    SOURCE_DIRECT = "direct"
    SOURCE_CHOICES = [(SOURCE_TEAM, "Team"), (SOURCE_DIRECT, "Direct")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="project_memberships")
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_DIRECT)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "project_memberships"
        constraints = [
            models.UniqueConstraint(fields=["project", "user"], name="unique_project_membership"),
        ]


class PermissionGrant(models.Model):
    SCOPE_ORG = "org"
    SCOPE_TEAM = "team"
    SCOPE_PROJECT = "project"
    SCOPE_ROOM = "room"
    SCOPE_CHOICES = [
        (SCOPE_ORG, "Org"),
        (SCOPE_TEAM, "Team"),
        (SCOPE_PROJECT, "Project"),
        (SCOPE_ROOM, "Room"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="grants")
    grantee = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="permission_grants")
    perm_key = models.CharField(max_length=100, db_index=True)
    scope_type = models.CharField(max_length=16, choices=SCOPE_CHOICES, default=SCOPE_ORG)
    scope_id = models.UUIDField(blank=True, null=True)
    granted_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="grants_given",
    )
    expires_at = models.DateTimeField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    revoked_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grants_revoked",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "permission_grants"


class PermissionRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="permission_requests")
    requester = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="permission_requests")
    perm_key = models.CharField(max_length=100)
    scope_type = models.CharField(max_length=16, default=PermissionGrant.SCOPE_ORG)
    scope_id = models.UUIDField(blank=True, null=True)
    reason = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    decided_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="permission_decisions",
    )
    decided_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "permission_requests"


class HRApplicant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="hr_applicants")
    email = models.EmailField()
    full_name = models.CharField(max_length=200)
    source = models.CharField(max_length=64, default="hr_webhook")
    reference = models.CharField(max_length=128, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    membership = models.ForeignKey(
        OrgMembership, on_delete=models.SET_NULL, null=True, blank=True, related_name="hr_applicants"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "hr_applicants"


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="audit_events")
    actor = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_events",
    )
    impersonator = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="impersonated_audit_events",
    )
    action = models.CharField(max_length=100, db_index=True)
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "audit_events"

    def save(self, *args, **kwargs):
        if self._state.adding:
            return super().save(*args, **kwargs)
        raise ValidationError("AuditEvent rows are append-only")

    def delete(self, *args, **kwargs):
        raise ValidationError("AuditEvent rows cannot be deleted")
