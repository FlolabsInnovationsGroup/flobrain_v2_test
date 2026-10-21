from django.contrib import admin

from organizations.models import (
    AuditEvent,
    OrgMembership,
    Organization,
    PermissionGrant,
    PermissionRequest,
    Project,
    Team,
)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    search_fields = ("name", "slug")


@admin.register(OrgMembership)
class OrgMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "org", "org_role", "employment_status")
    list_filter = ("org_role", "employment_status")


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "org", "is_active")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "org", "status")


@admin.register(PermissionGrant)
class PermissionGrantAdmin(admin.ModelAdmin):
    list_display = ("perm_key", "grantee", "org", "scope_type", "revoked_at")


@admin.register(PermissionRequest)
class PermissionRequestAdmin(admin.ModelAdmin):
    list_display = ("perm_key", "requester", "status", "created_at")


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("action", "actor", "org", "created_at")
    readonly_fields = [f.name for f in AuditEvent._meta.fields]

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
