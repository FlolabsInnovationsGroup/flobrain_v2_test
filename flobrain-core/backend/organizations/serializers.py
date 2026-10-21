from rest_framework import serializers

from organizations.models import AuditEvent, PermissionGrant, PermissionRequest
from organizations.permissions.registry import PERMISSION_CATALOG


class PermissionGrantSerializer(serializers.ModelSerializer):
    class Meta:
        model = PermissionGrant
        fields = (
            "id",
            "grantee",
            "perm_key",
            "scope_type",
            "scope_id",
            "expires_at",
            "revoked_at",
            "created_at",
        )
        read_only_fields = ("id", "revoked_at", "created_at")

    def validate_perm_key(self, value):
        if value not in PERMISSION_CATALOG:
            raise serializers.ValidationError("Unknown permission key")
        return value


class PermissionRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = PermissionRequest
        fields = (
            "id",
            "requester",
            "perm_key",
            "scope_type",
            "scope_id",
            "reason",
            "status",
            "decided_by",
            "decided_at",
            "created_at",
        )
        read_only_fields = ("id", "requester", "status", "decided_by", "decided_at", "created_at")

    def validate_perm_key(self, value):
        if value not in PERMISSION_CATALOG:
            raise serializers.ValidationError("Unknown permission key")
        return value


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = (
            "id",
            "actor",
            "impersonator",
            "action",
            "target_type",
            "target_id",
            "payload",
            "ip",
            "created_at",
        )
        read_only_fields = fields
