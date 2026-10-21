"""Org policy (Phase 17a): GET/PUT /orgs/{org}/policy (``policy.manage``).

Switching to ``private_only`` disables every customer AI key that points at a
host outside ``AI_SELF_HOSTED_HOSTS`` (no silent fallback afterwards).
"""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from core_v2.views import V2APIView
from organizations.models import OrgPolicy, Organization
from organizations.permissions import HasPerm, IsActiveOrgMember
from organizations.services.core import audit
from platform_api import pii


def _payload(org, policy):
    from brain.llm.policy import forced_private, self_hosted_hosts

    return {
        "org": str(org.id),
        "inference_scope": OrgPolicy.SCOPE_PRIVATE if forced_private() else (policy.inference_scope if policy else OrgPolicy.SCOPE_EXTERNAL),
        "pii_redaction": policy.pii_redaction if policy else "off",
        "data_region": policy.data_region if policy else "",
        "self_hosted_hosts": sorted(self_hosted_hosts()),
        # A detector must be set up (PII_DETECTOR, Q25). "regex" is basic: see platform_api/pii.py.
        "pii_redaction_available": pii.get_detector() is not None,
        "pii_detector": pii.describe(),
        "locked_private_only": forced_private(),
    }


class OrgPolicyView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="The org's AI and data policy")
    def get(self, request, org_id):
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        HasPerm("org.view").has_permission(request, self)
        return Response(_payload(org, OrgPolicy.objects.filter(org=org).first()))

    @extend_schema(summary="Change the policy (policy.manage)")
    def put(self, request, org_id):
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        HasPerm("policy.manage").has_permission(request, self)
        data = request.data if isinstance(request.data, dict) else {}
        policy = OrgPolicy.objects.filter(org=org).first() or OrgPolicy(org=org)
        if "inference_scope" in data:
            if data["inference_scope"] not in OrgPolicy.SCOPES:
                return Response({"error": "invalid", "details": "inference_scope must be external_allowed or private_only"}, status=400)
            from brain.llm.policy import forced_private

            if forced_private() and data["inference_scope"] != OrgPolicy.SCOPE_PRIVATE:
                return Response({"error": "locked", "details": "This installation only allows private_only"}, status=409)
            policy.inference_scope = data["inference_scope"]
        if "pii_redaction" in data:
            if data["pii_redaction"] not in OrgPolicy.REDACTION:
                return Response({"error": "invalid", "details": "pii_redaction must be off, external_only or always"}, status=400)
            if data["pii_redaction"] != "off" and pii.get_detector() is None:
                return Response({"error": "not_configured", "details": "PII redaction needs a detector. None is set up on this server."}, status=501)
            policy.pii_redaction = data["pii_redaction"]
        if "data_region" in data:
            region = str(data.get("data_region") or "")
            if len(region) > 32 or not all(c.isalnum() or c == "-" for c in region):
                return Response({"error": "invalid", "details": "data_region must be a region code"}, status=400)
            policy.data_region = region
        policy.updated_by = request.user
        policy.save()
        disabled = 0
        if policy.inference_scope == OrgPolicy.SCOPE_PRIVATE:
            disabled = _disable_external_keys(org)
        audit(
            request.user,
            "policy.update",
            payload={"inference_scope": policy.inference_scope, "pii_redaction": policy.pii_redaction, "keys_disabled": disabled},
            request=request,
            org=org,
        )
        return Response({**_payload(org, policy), "keys_disabled": disabled})


def _disable_external_keys(org) -> int:
    import urllib.parse

    from brain.llm.policy import self_hosted_hosts
    from integrations.models import AICredential

    private = self_hosted_hosts()
    count = 0
    for key in AICredential.objects.filter(org=org).exclude(status=AICredential.STATUS_DISABLED):
        if (urllib.parse.urlparse(key.base_url).hostname or "").lower() not in private:
            key.status, key.last_error = AICredential.STATUS_DISABLED, "private_only"
            key.save(update_fields=["status", "last_error", "updated_at"])
            count += 1
    return count
