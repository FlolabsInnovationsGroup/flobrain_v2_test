"""Consent registry, social accounts and publishing (Phase 9d).

Flags: ``content_studio`` for consent and tagging; ``social_publishing`` for
accounts and publish jobs (501 when off). Keys: ``consent.manage``,
``social.connect``, ``content.approve`` (admins by default; grantable).
A member may submit a post for approval; they cannot approve it.
"""

import base64
import hashlib
import json
import secrets
from datetime import timedelta

from django.conf import settings
from django.http import HttpResponseRedirect
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from content_studio import connectors, publishing
from content_studio.access import gate, invalid, not_found, sees_all, visible_assets, visible_projects
from content_studio.models import (
    SCOPES,
    AssetPerson,
    ConsentRecord,
    OAuthState,
    PublishJob,
    RenderJob,
    SocialAccount,
)
from core_v2.views import V2APIView, V2PublicAPIView
from integrations import crypto
from organizations.models import OrgMembership
from organizations.permissions import IsActiveOrgMember, can
from organizations.services.core import audit

PUBLISH_FLAG = "social_publishing"


class StudioView(V2APIView):
    permission_classes = [IsActiveOrgMember]


def _uuid(value):
    import uuid

    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _active_member(org, user_id):
    membership = OrgMembership.objects.filter(org=org, user_id=_uuid(user_id)).select_related("user").first()
    return membership.user if membership is not None and membership.is_active_member else None


def _consent_payload(c):
    return {
        "id": str(c.id),
        "person_user": str(c.person_user_id) if c.person_user_id else None,
        "person_name": c.person_name,
        "scope": c.scope,
        "media_asset": str(c.media_asset_id) if c.media_asset_id else None,
        "granted_at": c.granted_at.isoformat(),
        "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
    }


class ConsentListView(StudioView):
    @extend_schema(summary="Consent records (yours, or all with consent.manage)")
    def get(self, request, org_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        qs = ConsentRecord.objects.filter(org=org)
        if not can(request.user, "consent.manage", org):
            qs = qs.filter(person_user=request.user)
        return Response([_consent_payload(c) for c in qs.order_by("-granted_at")[:500]])

    @extend_schema(summary="Record consent (for yourself, or anyone with consent.manage)")
    def post(self, request, org_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        data = request.data or {}
        scope = data.get("scope")
        if scope not in SCOPES:
            return invalid(f"scope must be one of {', '.join(SCOPES)}")
        manager = can(request.user, "consent.manage", org)
        person = None
        if data.get("person_user"):
            person = _active_member(org, data["person_user"])
            if person is None:
                return not_found("Member not found")
        elif not data.get("person_email"):
            person = request.user
        if not manager and person != request.user:
            return Response({"error": "permission_denied", "details": "You record your own consent"}, status=403)
        asset = None
        if data.get("media_asset"):
            asset_id = _uuid(data["media_asset"])
            asset = visible_assets(request.user, org).filter(pk=asset_id).first() if asset_id else None
            if asset is None and asset_id and person == request.user:
                from content_studio.models import MediaAsset

                asset = MediaAsset.objects.filter(org=org, pk=asset_id, people__person_user=request.user).first()
            if asset is None:
                return not_found("Asset not found")
        row = ConsentRecord.objects.create(
            org=org,
            person_user=person,
            person_name=str(data.get("person_name") or (person.username if person else "") or "")[:120],
            person_email=str(data.get("person_email") or "")[:254] if person is None else "",
            scope=scope,
            media_asset=asset,
            recorded_by=request.user,
        )
        audit(request.user, "consent.grant", target=row, payload={"scope": scope}, request=request, org=org)
        return Response(_consent_payload(row), status=201)


class ConsentRevokeView(StudioView):
    @extend_schema(summary="Revoke consent (the person, or consent.manage). Blocks pending publishes.")
    def post(self, request, org_id, consent_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        row = ConsentRecord.objects.filter(org=org, pk=consent_id).first()
        if row is None or not (row.person_user_id == request.user.id or can(request.user, "consent.manage", org)):
            return not_found("Consent not found")
        if row.revoked_at is None:
            row.revoked_at = timezone.now()
            row.save(update_fields=["revoked_at"])
            audit(request.user, "consent.revoke", target=row, request=request, org=org)
        return Response(_consent_payload(row))


def _people_payload(request, org, asset):
    manager = can(request.user, "consent.manage", org)
    rows = []
    for p in AssetPerson.objects.filter(asset=asset).select_related("person_user").order_by("person_name", "id"):
        rows.append(
            {
                "id": str(p.id),
                "user_id": str(p.person_user_id) if p.person_user_id else None,
                "name": p.person_user.username if p.person_user_id else (p.person_name or p.person_email or "Unnamed person"),
                "email": p.person_email if (manager and not p.person_user_id) else None,
                "consented": publishing.has_consent(org, asset, p),
            }
        )
    return {"asset": str(asset.id), "people": len(rows), "tagged": rows, "face_count": asset.face_count, "can_remove": manager}


class AssetPeopleView(StudioView):
    @extend_schema(summary="People tagged in an asset, each with whether they consented to public posts")
    def get(self, request, org_id, asset_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        asset = visible_assets(request.user, org).filter(pk=asset_id).first()
        if asset is None:
            return not_found("Asset not found")
        return Response(_people_payload(request, org, asset))

    @extend_schema(summary="Tag the people who appear in an asset (managers replace; others can only add)")
    def put(self, request, org_id, asset_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        asset = visible_assets(request.user, org).filter(pk=asset_id).first()
        if asset is None:
            return not_found("Asset not found")
        people = (request.data or {}).get("people")
        if not isinstance(people, list) or len(people) > 100:
            return invalid("people must be a list (at most 100)")
        wanted = {}
        for item in people:
            if not isinstance(item, dict):
                return invalid("each person is an object")
            if item.get("user_id"):
                user = _active_member(org, item["user_id"])
                if user is None:
                    return not_found("Member not found")
                wanted[f"u:{user.id}"] = AssetPerson(asset=asset, person_user=user, tagged_by=request.user)
            elif item.get("email") or item.get("name"):
                email = str(item.get("email") or "")[:254].strip().lower()
                name = str(item.get("name") or "")[:120].strip()
                wanted[f"e:{email}:{name.lower()}"] = AssetPerson(
                    asset=asset, person_name=name, person_email=email, tagged_by=request.user
                )
            else:
                return invalid("each person needs user_id, or name/email")
        existing = {publishing._person_key(p): p for p in AssetPerson.objects.filter(asset=asset)}
        manager = can(request.user, "consent.manage", org)
        removed = [p for key, p in existing.items() if key not in wanted]
        if removed and not manager:
            # Removing a tag weakens the consent check, so only consent.manage may do it.
            return Response(
                {"error": "permission_denied", "details": "Only consent managers can remove people tags"}, status=403
            )
        AssetPerson.objects.filter(pk__in=[p.pk for p in removed]).delete()
        AssetPerson.objects.bulk_create([p for key, p in wanted.items() if key not in existing])
        count = AssetPerson.objects.filter(asset=asset).count()
        audit(
            request.user,
            "content.people_tag",
            target=asset,
            payload={"people": count, "removed": len(removed)},
            request=request,
            org=org,
        )
        return Response({**_people_payload(request, org, asset), "people": count})


def describe_problems(org, problems):
    """Add display names to consent problems (people and assets the viewer may see anyway)."""
    from content_studio.models import MediaAsset
    from users.models import User

    user_ids = {_uuid(p.get("person")) for p in problems if p.get("problem") == "missing_consent"} - {None}
    names = {str(u.id): u.username for u in User.objects.filter(pk__in=user_ids)}
    assets = {str(a.id): a.name for a in MediaAsset.objects.filter(org=org, pk__in=[p["asset"] for p in problems])}
    out = []
    for p in problems:
        item = dict(p)
        item["asset_name"] = assets.get(p["asset"], "")
        if p.get("problem") == "missing_consent":
            item["person_name"] = names.get(str(p.get("person")), str(p.get("person") or ""))
        out.append(item)
    return out


class ProjectConsentView(StudioView):
    @extend_schema(summary="Consent check on what a render of this project would contain (sources and brand media)")
    def get(self, request, org_id, project_id):
        from content_studio import renders

        org, error = gate(request, self, org_id)
        if error:
            return error
        project = visible_projects(request.user, org).filter(pk=project_id).first()
        if project is None:
            return not_found("Project not found")
        draft = RenderJob(org=org, project=project, spec=renders.build_spec(project, "16x9_1080"))
        problems = describe_problems(org, publishing.consent_problems(draft))
        return Response({"ok": not problems, "problems": problems})


class RenderConsentView(StudioView):
    @extend_schema(summary="Consent check on everything in a finished render (what approval and publish check)")
    def get(self, request, org_id, render_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        render = RenderJob.objects.filter(org=org, pk=render_id, project__in=visible_projects(request.user, org)).first()
        if render is None:
            return not_found("Render not found")
        problems = describe_problems(org, publishing.consent_problems(render))
        return Response({"ok": not problems, "problems": problems})


# --- social accounts --------------------------------------------------------------


def _account_payload(a):
    return {
        "id": str(a.id),
        "platform": a.platform,
        "display_name": a.display_name,
        "status": a.status,
        "private_only": a.private_only,
        "scopes": a.scopes,
    }


def _redirect_uri(platform):
    base = getattr(settings, "PUBLIC_API_BASE_URL", "") or "http://localhost:8000"
    return f"{base.rstrip('/')}/api/v2/oauth/callback/{platform}"


class PlatformListView(StudioView):
    @extend_schema(summary="Social platforms and whether each is configured")
    def get(self, request, org_id):
        org, error = gate(request, self, org_id, flag=PUBLISH_FLAG)
        if error:
            return error
        return Response(connectors.platforms())


class SocialAccountListView(StudioView):
    @extend_schema(summary="Connected social accounts (never their tokens)")
    def get(self, request, org_id):
        org, error = gate(request, self, org_id, flag=PUBLISH_FLAG)
        if error:
            return error
        return Response([_account_payload(a) for a in SocialAccount.objects.filter(org=org).order_by("platform")])


class SocialAccountDetailView(StudioView):
    @extend_schema(summary="Disconnect a social account (social.connect)")
    def delete(self, request, org_id, account_id):
        org, error = gate(request, self, org_id, perm="social.connect", flag=PUBLISH_FLAG)
        if error:
            return error
        account = SocialAccount.objects.filter(org=org, pk=account_id).first()
        if account is None:
            return not_found("Account not found")
        account.status = SocialAccount.STATUS_REVOKED
        account.token_ciphertext = b""
        account.save(update_fields=["status", "token_ciphertext"])
        audit(request.user, "social.disconnect", target=account, request=request, org=org)
        return Response(status=204)


class SocialConnectView(StudioView):
    @extend_schema(summary="Start OAuth: returns the provider's authorize URL (single-use state, PKCE)")
    def post(self, request, org_id, platform):
        org, error = gate(request, self, org_id, perm="social.connect", flag=PUBLISH_FLAG)
        if error:
            return error
        connector = connectors.get(platform)
        if connector is None:
            return not_found("Unknown platform")
        if not connector.configured() or not crypto.is_configured():
            return Response({"error": "not_configured", "details": f"{platform} is not configured"}, status=501)
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        row = OAuthState(
            org=org,
            user=request.user,
            platform=platform,
            state_hash=hashlib.sha256(state.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        row.verifier_ciphertext = crypto.encrypt(verifier, row.id, org.id)
        row.key_version = crypto.current_key_version()
        row.save()
        return Response({"authorize_url": connector.authorize_url(state, challenge, _redirect_uri(platform))})


class OAuthCallbackView(V2PublicAPIView):
    """Authenticated by ``state`` only (single use, 10 minutes). It does **not** connect the account:
    it parks the tokens and hands this browser a one-time code. The account is created only when the
    user who started the flow confirms with that code while signed in (``…/social-accounts/confirm``),
    so a link sent to someone else cannot attach their channel to the sender's org."""

    @extend_schema(summary="OAuth callback (fixed redirect URI)")
    def get(self, request, platform):
        from urllib.parse import quote

        frontend = (getattr(settings, "FRONTEND_BASE_URL", "") or "").rstrip("/")
        state = request.query_params.get("state") or ""
        code = request.query_params.get("code") or ""
        digest = hashlib.sha256(state.encode()).hexdigest()
        known = OAuthState.objects.filter(state_hash=digest, platform=platform).select_related("org").first()

        def done(result, confirm=""):
            # Back to the org's Studio accounts tab when the state is known; the site root otherwise.
            page = f"/w/{quote(known.org.slug)}/studio?tab=accounts&" if known is not None else "/?"
            suffix = f"&confirm={confirm}&platform={quote(platform)}" if confirm else ""
            return HttpResponseRedirect(f"{frontend}{page}result={result}{suffix}")

        row = known if known is not None and known.used_at is None else None
        if row is None or row.expires_at <= timezone.now() or not code:
            return done("invalid_state")
        if not OAuthState.objects.filter(pk=row.pk, used_at__isnull=True).update(used_at=timezone.now()):
            return done("invalid_state")  # raced: someone used it first
        connector = connectors.get(platform)
        if connector is None or not connector.configured():
            return done("not_configured")
        try:
            verifier = crypto.decrypt(row.verifier_ciphertext, row.id, row.org_id, row.key_version)
            result = connector.exchange_code(code, verifier, _redirect_uri(platform))
        except (connectors.ConnectorError, crypto.CredentialCryptoError):
            return done("exchange_failed")
        confirm = secrets.token_urlsafe(24)
        row.result_ciphertext = crypto.encrypt(json.dumps(result), row.id, row.org_id)
        row.key_version = crypto.current_key_version()
        row.confirm_hash = hashlib.sha256(confirm.encode()).hexdigest()
        row.save(update_fields=["result_ciphertext", "key_version", "confirm_hash"])
        return done("confirm", confirm)


class SocialConfirmView(StudioView):
    @extend_schema(summary="Finish connecting: the user who started the flow confirms with the one-time code")
    def post(self, request, org_id):
        org, error = gate(request, self, org_id, perm="social.connect", flag=PUBLISH_FLAG)
        if error:
            return error
        code = str((request.data or {}).get("code") or "")
        digest = hashlib.sha256(code.encode()).hexdigest()
        row = OAuthState.objects.filter(
            org=org, user=request.user, confirm_hash=digest, confirmed_at__isnull=True, used_at__isnull=False
        ).first()
        if not code or row is None or row.expires_at + timedelta(minutes=10) <= timezone.now():
            return not_found("Nothing to confirm")
        if not OAuthState.objects.filter(pk=row.pk, confirmed_at__isnull=True).update(confirmed_at=timezone.now()):
            return not_found("Nothing to confirm")
        connector = connectors.get(row.platform)
        try:
            result = json.loads(crypto.decrypt(row.result_ciphertext, row.id, org.id, row.key_version))
        except crypto.CredentialCryptoError:
            return Response({"error": "expired", "details": "Start again"}, status=409)
        account = SocialAccount(
            org=org,
            platform=row.platform,
            display_name=str(result.get("display_name") or row.platform)[:120],
            external_account_id=str(result.get("account_id") or "")[:120],
            scopes=list(result.get("scopes") or [])[:20],
            private_only=bool(connector and connector.unaudited_private),
            connected_by=request.user,
        )
        account.token_ciphertext = crypto.encrypt(json.dumps(result.get("tokens") or {}), account.id, org.id)
        account.key_version = crypto.current_key_version()
        account.save()
        OAuthState.objects.filter(pk=row.pk).update(result_ciphertext=None)
        audit(request.user, "social.connect", target=account, payload={"platform": row.platform}, request=request, org=org)
        return Response(_account_payload(account), status=201)


# --- publish jobs -------------------------------------------------------------------


def _demo_publish_due(org):
    """Demo mode only: stand in for the ``tick_content`` scheduler for this org."""
    if getattr(settings, "DEMO_MODE", False):
        publishing.publish_due(org=org)


def _job_or_404(request, org, job_id):
    qs = PublishJob.objects.filter(org=org, pk=job_id).select_related("render", "social_account")
    if not (can(request.user, "content.approve", org) or can(request.user, "content.publish", org)):
        qs = qs.filter(project__in=visible_projects(request.user, org))
    return qs.first()


def _clean_copy(data, job=None):
    out = {}
    if job is None or "title" in data:
        title = str(data.get("title") or "").strip()
        if not title or len(title) > 200:
            raise ValueError("title is required (at most 200 characters)")
        out["title"] = title
    if "description" in data:
        out["description"] = str(data.get("description") or "")[:5000]
    if "hashtags" in data:
        tags = data.get("hashtags") or []
        if not isinstance(tags, list) or len(tags) > 30 or not all(isinstance(t, str) and 0 < len(t) <= 60 for t in tags):
            raise ValueError("hashtags must be a list of short strings")
        out["hashtags"] = tags
    if "scheduled_at" in data:
        value = data.get("scheduled_at")
        if value in (None, ""):
            out["scheduled_at"] = None
        else:
            try:
                when = parse_datetime(str(value))
            except ValueError:
                when = None
            if when is None or timezone.is_naive(when):
                raise ValueError("scheduled_at must be an ISO date-time with a time zone")
            out["scheduled_at"] = when
    return out


class PublishJobListCreateView(StudioView):
    @extend_schema(summary="Publish jobs you can see")
    def get(self, request, org_id):
        org, error = gate(request, self, org_id, flag=PUBLISH_FLAG)
        if error:
            return error
        _demo_publish_due(org)
        qs = PublishJob.objects.filter(org=org).select_related("render", "social_account")
        if not (can(request.user, "content.approve", org) or can(request.user, "content.publish", org)):
            qs = qs.filter(project__in=visible_projects(request.user, org))
        return Response([publishing.payload(j) for j in qs.order_by("-created_at")[:200]])

    @extend_schema(summary="Submit a post for approval (it never publishes without approval)")
    def post(self, request, org_id):
        org, error = gate(request, self, org_id, flag=PUBLISH_FLAG)
        if error:
            return error
        data = request.data or {}
        project = visible_projects(request.user, org).filter(pk=_uuid(data.get("project"))).first() if _uuid(data.get("project")) else None
        if project is None:
            return not_found("Project not found")
        render = RenderJob.objects.filter(
            org=org, project=project, pk=_uuid(data.get("render")), status=RenderJob.STATUS_SUCCEEDED
        ).first() if _uuid(data.get("render")) else None
        if render is None:
            return invalid("render must be a finished render of this project")
        account = SocialAccount.objects.filter(
            org=org, pk=_uuid(data.get("social_account")), status=SocialAccount.STATUS_CONNECTED
        ).first() if _uuid(data.get("social_account")) else None
        if account is None:
            return not_found("Social account not found")
        try:
            fields = _clean_copy(data)
        except ValueError as exc:
            return invalid(exc)
        job = PublishJob.objects.create(org=org, project=project, render=render, social_account=account, created_by=request.user, **fields)
        audit(request.user, "content.publish_submit", target=job, request=request, org=org)
        return Response(publishing.payload(job), status=201)


class PublishJobDetailView(StudioView):
    @extend_schema(summary="Edit copy or time; any change resets approval")
    def patch(self, request, org_id, job_id):
        org, error = gate(request, self, org_id, flag=PUBLISH_FLAG)
        if error:
            return error
        job = _job_or_404(request, org, job_id)
        if job is None:
            return not_found("Publish job not found")
        if job.status in (PublishJob.PUBLISHING, PublishJob.PUBLISHED, PublishJob.CANCELLED):
            return Response({"error": "locked", "details": f"The job is {job.status}"}, status=409)
        try:
            fields = _clean_copy(request.data or {}, job)
        except ValueError as exc:
            return invalid(exc)
        seen_status = job.status
        before = publishing.approval_hash(job)
        for key, value in fields.items():
            setattr(job, key, value)
        changes = dict(fields)
        if publishing.approval_hash(job) != before:
            changes.update(status=PublishJob.AWAITING, approved_by=None, approved_at=None, approval_hash="")
        # Only the fields that changed, and only if nobody moved the job meanwhile (e.g. publishing).
        if changes and not PublishJob.objects.filter(pk=job.pk, status=seen_status).update(**changes):
            return Response({"error": "locked", "details": "The job changed meanwhile"}, status=409)
        job.refresh_from_db()
        return Response(publishing.payload(job))


class PublishJobApproveView(StudioView):
    @extend_schema(summary="Approve exactly what you reviewed (hash); consent is checked now and again at publish")
    def post(self, request, org_id, job_id):
        from jobs.queue import enqueue

        org, error = gate(request, self, org_id, perm="content.approve", flag=PUBLISH_FLAG)
        if error:
            return error
        job = PublishJob.objects.filter(org=org, pk=job_id).select_related("render", "social_account", "project").first()
        if job is None:
            return not_found("Publish job not found")
        if job.status != PublishJob.AWAITING:
            return Response({"error": "not_pending", "details": f"The job is {job.status}"}, status=409)
        current = publishing.approval_hash(job)
        if (request.data or {}).get("hash") != current:
            return Response({"error": "changed", "details": "The post changed since you reviewed it", "hash": current}, status=409)
        problems = publishing.consent_problems(job.render)
        if problems:
            return Response({"error": "consent_missing", "details": "Consent is missing", "problems": problems}, status=409)
        new_status = PublishJob.SCHEDULED if job.scheduled_at and job.scheduled_at > timezone.now() else PublishJob.APPROVED
        # Conditional update: a cancel or edit that landed since we read the row wins.
        updated = PublishJob.objects.filter(pk=job.pk, status=PublishJob.AWAITING).update(
            approved_by=request.user, approved_at=timezone.now(), approval_hash=current, status=new_status
        )
        if not updated:
            return Response({"error": "not_pending", "details": "The job changed while approving"}, status=409)
        job.refresh_from_db()
        if publishing.approval_hash(job) != current:
            PublishJob.objects.filter(pk=job.pk).update(status=PublishJob.AWAITING, approved_by=None, approval_hash="")
            return Response({"error": "changed", "details": "The post changed while approving"}, status=409)
        audit(request.user, "content.publish_approve", target=job, payload={"hash": current}, request=request, org=org)
        if job.status == PublishJob.APPROVED:
            enqueue("content.publish", {"job_id": str(job.id)})
            job.refresh_from_db()
        return Response(publishing.payload(job))


class PublishJobCancelView(StudioView):
    @extend_schema(summary="Cancel a publish job that has not been published")
    def post(self, request, org_id, job_id):
        org, error = gate(request, self, org_id, flag=PUBLISH_FLAG)
        if error:
            return error
        job = _job_or_404(request, org, job_id)
        if job is None:
            return not_found("Publish job not found")
        updated = PublishJob.objects.filter(
            pk=job.pk, status__in=[PublishJob.AWAITING, PublishJob.APPROVED, PublishJob.SCHEDULED, PublishJob.FAILED]
        ).update(status=PublishJob.CANCELLED)
        if not updated:
            return Response({"error": "not_cancellable", "details": f"The job is {job.status}"}, status=409)
        job.refresh_from_db()
        return Response(publishing.payload(job))


class ContentCalendarView(StudioView):
    @extend_schema(summary="Scheduled and published posts between from and to")
    def get(self, request, org_id):
        org, error = gate(request, self, org_id, flag=PUBLISH_FLAG)
        if error:
            return error
        def _when(name, default):
            try:
                return parse_datetime(request.query_params.get(name) or "") or default
            except ValueError:
                return default

        start = _when("from", timezone.now() - timedelta(days=7))
        end = _when("to", timezone.now() + timedelta(days=30))
        if timezone.is_naive(start):
            start = timezone.make_aware(start)
        if timezone.is_naive(end):
            end = timezone.make_aware(end)
        _demo_publish_due(org)
        from django.db.models import Q

        # Scheduled posts in the window, and posts that went out straight after approval in it.
        qs = PublishJob.objects.filter(org=org).filter(
            Q(scheduled_at__gte=start, scheduled_at__lte=end)
            | Q(scheduled_at__isnull=True, status=PublishJob.PUBLISHED, approved_at__gte=start, approved_at__lte=end)
        ).select_related("render", "social_account")
        if not (can(request.user, "content.approve", org) or can(request.user, "content.publish", org) or sees_all(request.user, org)):
            qs = qs.filter(project__in=visible_projects(request.user, org))
        return Response([publishing.payload(j) for j in qs.order_by("scheduled_at", "approved_at")[:500]])

