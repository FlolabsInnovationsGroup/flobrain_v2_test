"""In-org marketplace (Phase 17e): buddies and Content Studio templates.

- ``GET /orgs/{org}/marketplace``: approved listings (managers also see pending/rejected; submitters see their own)
- ``POST /orgs/{org}/marketplace``: submit ``{kind, source}`` you own (``marketplace.submit``)
- ``POST /orgs/{org}/marketplace/{id}/approve|reject`` (``marketplace.manage``; no self-approval except the owner)
- ``POST /orgs/{org}/marketplace/{id}/withdraw`` (submitter or manager)
- ``POST /orgs/{org}/marketplace/{id}/install``: a private buddy copy (``buddy.create``) or a template copy (``content.manage``)
- ``POST /orgs/{org}/marketplace/{id}/versions``: the listing's owner publishes ``{changelog}`` as a new frozen
  snapshot of the same source; it waits for the same ``marketplace.manage`` approval as version 1
- ``POST /orgs/{org}/marketplace/installs/{install}/update``: replace *your* installed copy with the current
  approved version (only your copy changes; see ``_update_buddy`` for what is kept)
"""

import uuid

from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from core_v2.views import V2APIView
from marketplace.models import Install, Listing
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization
from organizations.permissions import HasPerm, IsActiveOrgMember
from organizations.permissions.engine import can
from organizations.services.core import audit

BUDDY_FIELDS = ("name", "description", "icon", "system_prompt", "preset_prompts", "allowed_tools", "default_model")


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def _payload(listing, full=False, copies=None):
    data = {
        "id": str(listing.id),
        "kind": listing.kind,
        "lineage": str(listing.lineage),
        "version": listing.version,
        "changelog": listing.changelog,
        "title": listing.title,
        "description": listing.description,
        "status": listing.status,
        "installs": listing.installs,
        "submitted_by": str(listing.submitted_by_id) if listing.submitted_by_id else None,
        "decided_at": listing.decided_at.isoformat() if listing.decided_at else None,
        "decision_note": listing.decision_note,
        "created_at": listing.created_at.isoformat(),
    }
    if full:
        data["snapshot"] = listing.snapshot
    if copies is not None:
        # The viewer's own copies from any version of this listing.
        mine = [c for c in copies if c.lineage == listing.lineage]
        data["my_copies"] = [{"install": str(c.id), "id": str(c.target_id), "version": c.version} for c in mine]
        data["update_available"] = listing.status == Listing.APPROVED and any(c.version < listing.version for c in mine)
    return data


def _my_copies(user, org):
    """The user's installs whose copy still exists (a deleted copy has nothing to update)."""
    from buddies.models import Buddy
    from content_studio.models import ContentTemplate

    installs = list(Install.objects.filter(org=org, user=user))
    buddies = {i.target_id for i in installs if i.kind == Listing.KIND_BUDDY}
    templates = {i.target_id for i in installs if i.kind == Listing.KIND_TEMPLATE}
    alive = set(Buddy.objects.filter(org=org, pk__in=buddies, created_by=user).values_list("pk", flat=True))
    alive |= set(ContentTemplate.objects.filter(org=org, pk__in=templates).values_list("pk", flat=True))
    return [i for i in installs if i.target_id in alive]


def _org(request, view, org_id, perm=None):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    if perm:
        HasPerm(perm).has_permission(request, view)
    return org


def _flag_for(kind):
    return "buddies" if kind == Listing.KIND_BUDDY else "content_studio"


def _flag_on(request, org, kind):
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    return effective_flag(org, membership, _flag_for(kind), default=False)


def _snapshot_buddy(request, org, source_id):
    from buddies.models import Buddy

    buddy = Buddy.objects.filter(org=org, pk=source_id, created_by=request.user, is_builtin=False).first()
    if buddy is None:
        return None, None
    snapshot = {field: getattr(buddy, field) for field in BUDDY_FIELDS}
    sources = dict(buddy.allowed_sources or {})
    # Room ids are the author's; installers search what *they* can read, or nothing.
    if sources.get("mode") == Buddy.SOURCES_ROOMS:
        sources = {"mode": Buddy.SOURCES_NONE, "source_types": sources.get("source_types") or ["doc", "room_message"]}
    snapshot["allowed_sources"] = sources
    return buddy, snapshot


def _snapshot_template(request, org, source_id):
    from content_studio.models import ContentTemplate

    template = ContentTemplate.objects.filter(org=org, pk=source_id, is_builtin=False).first()
    if template is None or not (template.created_by_id == request.user.id or can(request.user, "content.manage", org)):
        return None, None
    return template, {"name": template.name, "kind": template.kind, "spec": template.spec}


class ListingView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Marketplace listings")
    def get(self, request, org_id):
        org = _org(request, self, org_id)
        listings = Listing.objects.filter(org=org)
        manager = can(request.user, "marketplace.manage", org)
        if not manager:
            listings = listings.filter(Q(status=Listing.APPROVED) | Q(submitted_by=request.user))
        status = request.query_params.get("status")
        if status in dict(Listing.STATUS_CHOICES):
            listings = listings.filter(status=status)
        copies = _my_copies(request.user, org)
        return Response([_payload(l, full=True, copies=copies) for l in listings[:200]])

    @extend_schema(summary="Submit a buddy or template you own for approval")
    def post(self, request, org_id):
        org = _org(request, self, org_id, "marketplace.submit")
        data = _body(request)
        kind = data.get("kind")
        if kind not in (Listing.KIND_BUDDY, Listing.KIND_TEMPLATE):
            return Response({"error": "invalid", "details": "kind must be buddy or content_template"}, status=400)
        if not _flag_on(request, org, kind):
            return Response({"error": "not_implemented", "details": "That feature is not enabled"}, status=501)
        try:
            source_id = uuid.UUID(str(data.get("source")))
        except (TypeError, ValueError):
            return Response({"error": "invalid", "details": "source must be an id"}, status=400)
        snap = _snapshot_buddy if kind == Listing.KIND_BUDDY else _snapshot_template
        source, snapshot = snap(request, org, source_id)
        if source is None:
            return Response({"error": "not_found", "details": "Not found or not yours"}, status=404)
        try:
            with transaction.atomic():
                listing = Listing.objects.create(
                    org=org,
                    kind=kind,
                    source_id=source_id,
                    title=str(snapshot["name"])[:80],
                    description=str(data.get("description") or getattr(source, "description", "") or "")[:500],
                    snapshot=snapshot,
                    submitted_by=request.user,
                )
        except IntegrityError:
            return Response({"error": "conflict", "details": "Already waiting for approval"}, status=409)
        audit(request.user, "marketplace.submit", target=listing, payload={"kind": kind, "source": str(source_id)}, request=request, org=org)
        return Response(_payload(listing, full=True), status=201)


class ListingDecisionView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Approve or reject a listing (marketplace.manage)")
    def post(self, request, org_id, listing_id, decision):
        org = _org(request, self, org_id, "marketplace.manage")
        if decision not in ("approve", "reject"):
            return Response({"error": "not_found"}, status=404)
        listing = get_object_or_404(Listing, pk=listing_id, org=org)
        is_owner = OrgMembership.objects.filter(org=org, user=request.user, org_role=OrgMembership.ORG_ROLE_OWNER).exists()
        if listing.submitted_by_id == request.user.id and not is_owner:
            return Response({"error": "permission_denied", "details": "Someone else must approve your listing"}, status=403)
        status = Listing.APPROVED if decision == "approve" else Listing.REJECTED
        note = str(_body(request).get("note") or "")[:500]
        with transaction.atomic():
            updated = Listing.objects.filter(pk=listing.pk, status=Listing.PENDING).update(
                status=status, decided_by=request.user, decided_at=timezone.now(), decision_note=note
            )
            if not updated:
                return Response({"error": "conflict", "details": "This listing is not pending"}, status=409)
            superseded = 0
            if status == Listing.APPROVED:
                # One available version per listing: the one just approved replaces the older one.
                superseded = (
                    Listing.objects.filter(lineage=listing.lineage, status=Listing.APPROVED).exclude(pk=listing.pk).update(status=Listing.SUPERSEDED)
                )
        listing.refresh_from_db()
        audit(
            request.user,
            f"marketplace.{decision}",
            target=listing,
            payload={"note": note, "version": listing.version, "superseded": superseded},
            request=request,
            org=org,
        )
        return Response(_payload(listing, full=True))


class ListingWithdrawView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Withdraw a listing (submitter or marketplace.manage)")
    def post(self, request, org_id, listing_id):
        org = _org(request, self, org_id)
        listing = get_object_or_404(Listing, pk=listing_id, org=org)
        if listing.submitted_by_id != request.user.id and not can(request.user, "marketplace.manage", org):
            return Response({"error": "not_found"}, status=404)
        if not Listing.objects.filter(pk=listing.pk, status__in=[Listing.PENDING, Listing.APPROVED]).update(status=Listing.WITHDRAWN):
            return Response({"error": "conflict", "details": "Already closed"}, status=409)
        audit(request.user, "marketplace.withdraw", target=listing, request=request, org=org)
        return Response(status=204)


class ListingInstallView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Install an approved listing as your own copy")
    def post(self, request, org_id, listing_id):
        org = _org(request, self, org_id)
        listing = get_object_or_404(Listing, pk=listing_id, org=org, status=Listing.APPROVED)
        if not _flag_on(request, org, listing.kind):
            return Response({"error": "not_implemented", "details": "That feature is not enabled"}, status=501)
        if listing.kind == Listing.KIND_BUDDY:
            result = self._buddy(request, org, listing)
        else:
            result = self._template(request, org, listing)
        if isinstance(result, Response):
            return result
        install = Install.objects.create(
            org=org,
            listing=listing,
            lineage=listing.lineage,
            version=listing.version,
            user=request.user,
            kind=listing.kind,
            target_id=result["id"],
        )
        Listing.objects.filter(pk=listing.pk).update(installs=F("installs") + 1)
        audit(
            request.user,
            "marketplace.install",
            target=listing,
            payload={"created": result["id"], "version": listing.version},
            request=request,
            org=org,
        )
        return Response({**result, "install": str(install.id), "version": listing.version}, status=201)

    def _buddy(self, request, org, listing):
        from buddies.models import Buddy

        fields, dropped = _buddy_fields(request, self, org, listing.snapshot)
        if isinstance(fields, Response):
            return fields
        slug = f"{slugify(fields['name'])[:60] or 'buddy'}-{uuid.uuid4().hex[:8]}"
        buddy = Buddy.objects.create(org=org, slug=slug, created_by=request.user, **fields)
        return {"kind": listing.kind, "id": str(buddy.id), "dropped_tools": dropped}

    def _template(self, request, org, listing):
        from content_studio.models import ContentTemplate

        fields = _template_fields(request, self, listing)
        if isinstance(fields, Response):
            return fields
        template = ContentTemplate.objects.create(org=org, slug=f"t-{uuid.uuid4().hex[:10]}", created_by=request.user, **fields)
        return {"kind": listing.kind, "id": str(template.id)}


def _buddy_fields(request, view, org, snapshot, keep=()):
    """Buddy fields from a snapshot, checked against the installer's own access (like the Buddy Builder).
    Tools the installer does not hold are left out and reported. ``keep`` names snapshot keys not applied."""
    from buddies.services import BuddyInvalid, clean_definition, holds_tool

    HasPerm("buddy.create").has_permission(request, view)
    HasPerm("ai.use").has_permission(request, view)
    snapshot = {k: v for k, v in dict(snapshot).items() if k not in keep}
    tools = [t for t in snapshot.get("allowed_tools") or [] if holds_tool(request.user, org, str(t))]
    dropped = [t for t in snapshot.get("allowed_tools") or [] if t not in tools]
    snapshot["allowed_tools"] = tools
    try:
        return clean_definition(request.user, org, snapshot), dropped
    except BuddyInvalid as exc:
        return Response({"error": "invalid", "details": str(exc)}, status=400), dropped


def _template_fields(request, view, listing):
    from content_studio.views import _clean_spec

    HasPerm("content.manage").has_permission(request, view)
    try:
        spec = _clean_spec(dict(listing.snapshot.get("spec") or {}))
    except ValueError as exc:
        return Response({"error": "invalid", "details": str(exc)}, status=400)
    return {
        "name": str(listing.snapshot.get("name") or listing.title)[:80],
        "kind": str(listing.snapshot.get("kind") or "custom")[:16],
        "spec": spec,
    }


class ListingVersionView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Publish a new version of your listing (waits for marketplace.manage approval)")
    def post(self, request, org_id, listing_id):
        org = _org(request, self, org_id, "marketplace.submit")
        listing = get_object_or_404(Listing, pk=listing_id, org=org)
        if listing.submitted_by_id != request.user.id:
            if listing.status != Listing.APPROVED and not can(request.user, "marketplace.manage", org):
                return Response({"error": "not_found"}, status=404)  # not visible to this user
            return Response({"error": "permission_denied", "details": "Only the person who offered it can publish a new version"}, status=403)
        current = Listing.objects.filter(org=org, lineage=listing.lineage, status=Listing.APPROVED).first()
        if current is None:
            return Response({"error": "conflict", "details": "Only an available listing can get a new version"}, status=409)
        if not _flag_on(request, org, current.kind):
            return Response({"error": "not_implemented", "details": "That feature is not enabled"}, status=501)
        data = _body(request)
        changelog = str(data.get("changelog") or "").strip()[:500]
        if not changelog:
            return Response({"error": "invalid", "details": "changelog is required: say what changed"}, status=400)
        snap = _snapshot_buddy if current.kind == Listing.KIND_BUDDY else _snapshot_template
        source, snapshot = snap(request, org, current.source_id)
        if source is None:
            return Response({"error": "not_found", "details": "The original is gone or no longer yours"}, status=404)
        if snapshot == current.snapshot:
            return Response({"error": "invalid", "details": f"Nothing changed since version {current.version}"}, status=400)
        latest = Listing.objects.filter(lineage=current.lineage).order_by("-version").values_list("version", flat=True).first()
        try:
            with transaction.atomic():
                version = Listing.objects.create(
                    org=org,
                    kind=current.kind,
                    source_id=current.source_id,
                    lineage=current.lineage,
                    version=latest + 1,
                    changelog=changelog,
                    title=str(snapshot["name"])[:80],
                    description=str(data.get("description") or current.description)[:500],
                    snapshot=snapshot,
                    submitted_by=request.user,
                )
        except IntegrityError:
            return Response({"error": "conflict", "details": "A new version is already waiting for approval"}, status=409)
        audit(
            request.user,
            "marketplace.version",
            target=version,
            payload={"lineage": str(current.lineage), "version": version.version},
            request=request,
            org=org,
        )
        return Response(_payload(version, full=True), status=201)


class InstallUpdateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Update your installed copy to the current approved version")
    def post(self, request, org_id, install_id):
        org = _org(request, self, org_id)
        # Only your own copy: someone else's install id is simply not found.
        install = get_object_or_404(Install, pk=install_id, org=org, user=request.user)
        current = Listing.objects.filter(org=org, lineage=install.lineage, status=Listing.APPROVED).first()
        if current is None or current.version <= install.version:
            return Response({"error": "conflict", "details": "Your copy is already the latest available version"}, status=409)
        if not _flag_on(request, org, current.kind):
            return Response({"error": "not_implemented", "details": "That feature is not enabled"}, status=501)
        if current.kind == Listing.KIND_BUDDY:
            result = self._update_buddy(request, org, install, current)
        else:
            result = self._update_template(request, org, install, current)
        if isinstance(result, Response):
            return result
        previous = install.version
        install.listing, install.version, install.updated_at = current, current.version, timezone.now()
        install.save(update_fields=["listing", "version", "updated_at"])
        audit(
            request.user,
            "marketplace.update",
            target=current,
            payload={"copy": result["id"], "from": previous, "to": current.version},
            request=request,
            org=org,
        )
        return Response({**result, "install": str(install.id), "version": current.version})

    def _gone(self, install):
        install.delete()
        return Response({"error": "not_found", "details": "Your copy no longer exists; install it again"}, status=404)

    def _update_buddy(self, request, org, install, current):
        """Replaces every field the listing carries (name, description, icon, prompt, presets, tools, model).
        Kept: who it is shared with, and the rooms the installer picked for it to search (listings never
        carry room ids, so a rooms setting on the copy is always the installer's own choice)."""
        from buddies.models import Buddy
        from buddies.services import REAPPROVAL_FIELDS

        HasPerm("buddy.create").has_permission(request, self)
        HasPerm("ai.use").has_permission(request, self)
        buddy = Buddy.objects.filter(org=org, pk=install.target_id, created_by=request.user, is_builtin=False).first()
        if buddy is None:
            return self._gone(install)
        keep = ("allowed_sources",) if (buddy.allowed_sources or {}).get("mode") == Buddy.SOURCES_ROOMS else ()
        fields, dropped = _buddy_fields(request, self, org, current.snapshot, keep=keep)
        if isinstance(fields, Response):
            return fields
        changed = {k for k, v in fields.items() if getattr(buddy, k) != v}
        for key, value in fields.items():
            setattr(buddy, key, value)
        reopened = False
        if buddy.share_status == Buddy.SHARE_APPROVED and buddy.visibility != Buddy.VIS_PRIVATE and REAPPROVAL_FIELDS & changed:
            # Same rule as editing in the Buddy Builder: people it is shared with approved the old behaviour.
            buddy.share_status, buddy.share_target, buddy.share_team = Buddy.SHARE_PENDING, buddy.visibility, buddy.team
            reopened = True
        buddy.save()
        return {"kind": current.kind, "id": str(buddy.id), "dropped_tools": dropped, "kept": list(keep), "share_reopened": reopened}

    def _update_template(self, request, org, install, current):
        """Templates have no per-copy settings, so an update is the same as installing again."""
        from content_studio.models import ContentTemplate

        fields = _template_fields(request, self, current)
        if isinstance(fields, Response):
            return fields
        template = ContentTemplate.objects.filter(org=org, pk=install.target_id, is_builtin=False).first()
        if template is None:
            return self._gone(install)
        for key, value in fields.items():
            setattr(template, key, value)
        template.save()
        return {"kind": current.kind, "id": str(template.id)}
