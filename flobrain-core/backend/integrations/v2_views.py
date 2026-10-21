"""BYOK endpoints (Phase 7k).

GET/POST /api/v2/orgs/{org}/credentials
PATCH/DELETE /api/v2/orgs/{org}/credentials/{id}

Checks: active member (403) → ``ai.use`` (403) → flag ``byok`` (501) →
encryption key configured (501). The secret is accepted on create or rotate
and never returned. Personal keys of other users are 404 for everyone.
"""

import re
import uuid
from datetime import timezone as dt_timezone

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied, Throttled
from rest_framework.response import Response

from brain.throttles import AISendThrottle
from core_v2.views import V2APIView
from integrations import crypto
from integrations.credentials import (
    allowed_hosts,
    can_manage_org_keys,
    check_credential,
    demo_provider_enabled,
    normalize_base_url,
    payload,
    private_only_blocks,
    providers,
    visible_credentials,
)
from integrations.models import AICredential
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization
from organizations.permissions import HasPerm, IsActiveOrgMember
from organizations.services.core import audit

SECRET_RE = re.compile(r"^[\x21-\x7e]{8,512}$")  # printable, no spaces


def _bad(details):
    return Response({"error": "invalid", "details": details}, status=400)


def _private_only():
    return Response(
        {"error": "private_only", "details": "This organization only allows self-hosted models, so external keys can't be used"},
        status=409,
    )


def _gate(request, view, org_id):
    """Return (org, error_response)."""
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    HasPerm("ai.use").has_permission(request, view)
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, "byok", default=False):
        return org, Response({"error": "not_implemented", "details": "BYOK is not enabled"}, status=501)
    if not crypto.is_configured():
        return org, Response(
            {"error": "not_configured", "details": "Credential encryption is not configured"}, status=501
        )
    return org, None


def _throttle(request, view):
    throttle = AISendThrottle()
    if not throttle.allow_request(request, view):
        raise Throttled(wait=throttle.wait())


def _store_secret(credential, secret):
    credential.ciphertext = crypto.encrypt(secret, credential.id, credential.org_id)
    credential.key_version = crypto.current_key_version()
    credential.last4 = secret[-4:]


class CredentialListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="List AI keys you can see (never the secret)")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        rows = visible_credentials(request.user, org).order_by("-created_at")
        return Response([payload(row) for row in rows])

    @extend_schema(summary="Add an org or personal AI key; it is checked before it can be used")
    def post(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        data = request.data or {}
        scope = (data.get("scope") or AICredential.SCOPE_PERSONAL).strip()
        if scope not in (AICredential.SCOPE_ORG, AICredential.SCOPE_PERSONAL):
            return _bad("scope must be org or personal")
        if scope == AICredential.SCOPE_ORG and not can_manage_org_keys(request.user, org):
            raise PermissionDenied("credential.manage is required for org keys")
        provider = str(data.get("provider") or "openai_compatible").strip()
        if provider not in providers():
            return _bad("unknown provider")
        base_url = normalize_base_url(provider, str(data.get("base_url") or ""))
        if base_url is None:
            return _bad("base_url must be https and on the allowed host list")
        if private_only_blocks(org, provider, base_url):
            return _private_only()
        secret = data.get("secret") or ""
        if not isinstance(secret, str) or not SECRET_RE.match(secret):
            return _bad("secret must be 8 to 512 printable characters without spaces")
        expires_at = None
        if data.get("expires_at"):
            try:
                expires_at = parse_datetime(str(data["expires_at"]))
            except ValueError:
                expires_at = None
            if expires_at is None:
                return _bad("expires_at must be an ISO datetime")
            if timezone.is_naive(expires_at):
                expires_at = timezone.make_aware(expires_at, dt_timezone.utc)  # a date without zone is UTC
        _throttle(request, self)
        credential = AICredential(
            id=uuid.uuid4(),
            org=org,
            owner=request.user if scope == AICredential.SCOPE_PERSONAL else None,
            provider=provider,
            base_url=base_url,
            label=str(data.get("label") or "")[:80],
            expires_at=expires_at,
            created_by=request.user,
            status=AICredential.STATUS_PENDING,
        )
        _store_secret(credential, secret)
        credential.save()
        audit(request.user, "credential.create", target=credential, payload={"scope": scope}, request=request, org=org)
        check_credential(credential)
        return Response(payload(credential), status=201)


class CredentialDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def _get(self, request, org, credential_id):
        credential = AICredential.objects.filter(org=org, pk=credential_id).first()
        if credential is None:
            return None
        if credential.owner_id is not None:
            return credential if credential.owner_id == request.user.id else None  # 404 for anyone else
        if not can_manage_org_keys(request.user, org):
            raise PermissionDenied("credential.manage is required for org keys")
        return credential

    @extend_schema(summary="Rename, disable, enable, re-check or rotate an AI key")
    def patch(self, request, org_id, credential_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        credential = self._get(request, org, credential_id)
        if credential is None:
            return Response({"error": "not_found", "details": "Credential not found"}, status=404)
        data = request.data or {}
        recheck = bool(data.get("recheck"))
        if "label" in data:
            credential.label = str(data.get("label") or "")[:80]
        if "secret" in data:
            secret = data.get("secret") or ""
            if not isinstance(secret, str) or not SECRET_RE.match(secret):
                return _bad("secret must be 8 to 512 printable characters without spaces")
            _store_secret(credential, secret)
            credential.status = AICredential.STATUS_PENDING
            recheck = True
        action = data.get("status")
        if action not in (None, "disabled", "enabled"):
            return _bad("status must be disabled or enabled")
        if action == "disabled":
            credential.status = AICredential.STATUS_DISABLED
            recheck = False
        elif action == "enabled" and credential.status == AICredential.STATUS_DISABLED:
            if private_only_blocks(org, credential.provider, credential.base_url):
                return _private_only()
            credential.status = AICredential.STATUS_PENDING
            recheck = True
        credential.save()
        audit(
            request.user,
            "credential.update",
            target=credential,
            payload={"status": credential.status, "rotated": "secret" in data},
            request=request,
            org=org,
        )
        if recheck and credential.status != AICredential.STATUS_DISABLED:
            _throttle(request, self)
            if credential.status != AICredential.STATUS_EXPIRED:
                credential.status = AICredential.STATUS_PENDING
            check_credential(credential)
        return Response(payload(credential))

    @extend_schema(summary="Delete an AI key")
    def delete(self, request, org_id, credential_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        credential = self._get(request, org, credential_id)
        if credential is None:
            return Response({"error": "not_found", "details": "Credential not found"}, status=404)
        audit(request.user, "credential.delete", target=credential, payload={"scope": credential.scope}, request=request, org=org)
        credential.delete()
        return Response(status=204)


class CredentialMetaView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="What the AI keys page needs: providers, allowed hosts, who can add org keys")
    def get(self, request, org_id):
        from brain.llm.policy import PRIVATE_ONLY, inference_scope

        org, error = _gate(request, self, org_id)
        if error:
            return error
        scope = inference_scope(org)
        return Response(
            {
                "providers": list(providers()),
                "allowed_hosts": sorted(allowed_hosts()),
                "can_manage_org_keys": can_manage_org_keys(request.user, org),
                "inference_scope": scope,
                "private_only": scope == PRIVATE_ONLY,
                "demo_provider": demo_provider_enabled(),
            }
        )
