"""Content Studio basics (Phase 9a): brand kits, templates, assets, projects."""

import re
import uuid

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from content_studio import storage
from content_studio.access import gate, invalid, not_found, visible_assets, visible_projects
from content_studio.models import BrandKit, ContentProject, ContentTemplate, MediaAsset
from content_studio.seeds import ensure_builtin_templates
from brain.throttles import AISendThrottle
from core_v2.throttles import V2UserThrottle
from core_v2.views import V2APIView
from organizations.permissions import IsActiveOrgMember
from organizations.services.core import audit

CONTENT_TYPES = {
    "video": {"video/mp4", "video/quicktime", "video/webm"},
    "audio": {"audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/ogg"},
    "image": {"image/png", "image/jpeg", "image/webp"},
}
PLATFORMS = {"youtube", "linkedin", "tiktok", "instagram", "facebook", "x"}
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class StudioView(V2APIView):
    permission_classes = [IsActiveOrgMember]


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _asset_payload(a, with_url=False):
    data = {
        "id": str(a.id),
        "kind": a.kind,
        "name": a.name,
        "content_type": a.content_type,
        "size_bytes": a.size_bytes,
        "status": a.status,
        "duration_seconds": a.duration_seconds,
        "width": a.width,
        "height": a.height,
        "has_transcript": bool(a.transcript_words),
        "transcript_status": a.transcript_status or ("done" if a.transcript_words else ""),
        "uploaded_by": str(a.uploaded_by_id) if a.uploaded_by_id else None,
        "created_at": a.created_at.isoformat(),
    }
    if with_url and a.status == MediaAsset.STATUS_READY:
        data["url"] = storage.presign_get(a.storage_key)
    return data


def _kit_payload(k):
    return {
        "id": str(k.id),
        "name": k.name,
        "logos": k.logos,
        "fonts": k.fonts,
        "colors": k.colors,
        "intro_asset": str(k.intro_asset_id) if k.intro_asset_id else None,
        "outro_asset": str(k.outro_asset_id) if k.outro_asset_id else None,
        "caption_style": k.caption_style,
        "watermark": k.watermark,
    }


def _template_payload(t):
    return {"id": str(t.id), "slug": t.slug, "name": t.name, "kind": t.kind, "spec": t.spec, "builtin": t.is_builtin}


def _project_payload(p):
    return {
        "id": str(p.id),
        "title": p.title,
        "owner": str(p.owner_id),
        "status": p.status,
        "source_assets": [str(a) for a in p.source_assets.values_list("id", flat=True)],
        "brand_kit": str(p.brand_kit_id) if p.brand_kit_id else None,
        "template": str(p.template_id) if p.template_id else None,
        "target_platforms": p.target_platforms,
        "updated_at": p.updated_at.isoformat(),
    }


# --- brand kits -----------------------------------------------------------------


def _clean_kit(user, org, data, partial=False):
    out = {}
    if not partial or "name" in data:
        name = str(data.get("name") or "").strip()
        if not name or len(name) > 80:
            raise ValueError("name is required (at most 80 characters)")
        out["name"] = name
    if "colors" in data:
        colors = data.get("colors") or {}
        if not isinstance(colors, dict) or len(colors) > 20 or not all(
            isinstance(v, str) and HEX.match(v) for v in colors.values()
        ):
            raise ValueError("colors must map names to #RRGGBB")
        out["colors"] = {str(k)[:30]: v for k, v in colors.items()}
    for field in ("fonts", "caption_style", "watermark"):
        if field in data:
            value = data.get(field) or {}
            if not isinstance(value, dict) or len(str(value)) > 4000:
                raise ValueError(f"{field} must be a small object")
            out[field] = value
    images = visible_assets(user, org).filter(kind=MediaAsset.KIND_IMAGE, status=MediaAsset.STATUS_READY)
    if "logos" in data:
        ids = [_uuid(v) for v in (data.get("logos") or [])][:10]
        if None in ids or images.filter(pk__in=ids).count() != len(set(ids)):
            raise ValueError("logos must be ready image assets you can see")
        out["logos"] = [str(i) for i in dict.fromkeys(ids)]
    for field in ("intro_asset", "outro_asset"):
        if field in data:
            value = data.get(field)
            if value in (None, ""):
                out[field] = None
                continue
            asset = visible_assets(user, org).filter(pk=_uuid(value), kind=MediaAsset.KIND_VIDEO, status="ready").first()
            if asset is None:
                raise ValueError(f"{field} must be a ready video asset you can see")
            out[field] = asset
    return out


class BrandKitListView(StudioView):
    @extend_schema(summary="Brand kits")
    def get(self, request, org_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        return Response([_kit_payload(k) for k in BrandKit.objects.filter(org=org).order_by("name")])

    @extend_schema(summary="Create a brand kit (content.manage)")
    def post(self, request, org_id):
        org, error = gate(request, self, org_id, perm="content.manage")
        if error:
            return error
        try:
            fields = _clean_kit(request.user, org, request.data or {})
        except ValueError as exc:
            return invalid(exc)
        kit = BrandKit.objects.create(org=org, created_by=request.user, **fields)
        audit(request.user, "content.brand_kit_create", target=kit, request=request, org=org)
        return Response(_kit_payload(kit), status=201)


class BrandKitDetailView(StudioView):
    @extend_schema(summary="Edit a brand kit (content.manage)")
    def patch(self, request, org_id, kit_id):
        org, error = gate(request, self, org_id, perm="content.manage")
        if error:
            return error
        kit = BrandKit.objects.filter(org=org, pk=kit_id).first()
        if kit is None:
            return not_found("Brand kit not found")
        try:
            fields = _clean_kit(request.user, org, request.data or {}, partial=True)
        except ValueError as exc:
            return invalid(exc)
        for key, value in fields.items():
            setattr(kit, key, value)
        kit.save()
        return Response(_kit_payload(kit))

    @extend_schema(summary="Delete a brand kit (content.manage)")
    def delete(self, request, org_id, kit_id):
        org, error = gate(request, self, org_id, perm="content.manage")
        if error:
            return error
        deleted, _ = BrandKit.objects.filter(org=org, pk=kit_id).delete()
        return Response(status=204) if deleted else not_found("Brand kit not found")


# --- templates ------------------------------------------------------------------


def _clean_spec(spec):
    if not isinstance(spec, dict) or len(str(spec)) > 20000:
        raise ValueError("spec must be an object (at most 20 KB)")
    res = spec.get("resolution")
    if res is not None and (
        not isinstance(res, list) or len(res) != 2 or not all(isinstance(v, int) and 16 <= v <= 4096 for v in res)
    ):
        raise ValueError("resolution must be [width, height] within 16..4096")
    duration = spec.get("duration_seconds")
    if duration is not None and (not isinstance(duration, (int, float)) or not 0.5 <= duration <= 600):
        raise ValueError("duration_seconds must be within 0.5..600")
    variables = spec.get("variables", {})
    if not isinstance(variables, dict) or len(variables) > 20:
        raise ValueError("variables must be an object with at most 20 fields")
    for name, rule in variables.items():
        if not isinstance(name, str) or not name.isidentifier() or not isinstance(rule, dict):
            raise ValueError("each variable needs a simple name and a rule object")
        if rule.get("type", "string") != "string":
            raise ValueError("variables are strings")
        max_len = rule.get("maxLength", 500)
        if not isinstance(max_len, int) or isinstance(max_len, bool) or not 1 <= max_len <= 5000:
            raise ValueError("maxLength must be 1..5000")
        if "required" in rule and not isinstance(rule["required"], bool):
            raise ValueError("required must be true or false")
    return spec


class TemplateListView(StudioView):
    @extend_schema(summary="Templates (the FLOQ question card is built in)")
    def get(self, request, org_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        ensure_builtin_templates(org)
        return Response([_template_payload(t) for t in ContentTemplate.objects.filter(org=org).order_by("name")])

    @extend_schema(summary="Create a template (content.manage)")
    def post(self, request, org_id):
        org, error = gate(request, self, org_id, perm="content.manage")
        if error:
            return error
        data = request.data or {}
        name = str(data.get("name") or "").strip()[:80]
        kind = data.get("kind") or "custom"
        if not name or kind not in ContentTemplate.KINDS:
            return invalid("name and a known kind are required")
        try:
            spec = _clean_spec(data.get("spec") or {})
        except ValueError as exc:
            return invalid(exc)
        template = ContentTemplate.objects.create(
            org=org, slug=f"t-{uuid.uuid4().hex[:10]}", name=name, kind=kind, spec=spec, created_by=request.user
        )
        return Response(_template_payload(template), status=201)


class TemplateDetailView(StudioView):
    @extend_schema(summary="Edit a template (content.manage)")
    def patch(self, request, org_id, template_id):
        org, error = gate(request, self, org_id, perm="content.manage")
        if error:
            return error
        template = ContentTemplate.objects.filter(org=org, pk=template_id).first()
        if template is None:
            return not_found("Template not found")
        data = request.data or {}
        if "name" in data:
            template.name = str(data.get("name") or template.name).strip()[:80]
        if "spec" in data:
            try:
                template.spec = _clean_spec(data.get("spec"))
            except ValueError as exc:
                return invalid(exc)
        template.save()
        return Response(_template_payload(template))


# --- assets ---------------------------------------------------------------------


class AssetListCreateView(StudioView):
    @extend_schema(summary="Your media assets (all assets for managers and leads)")
    def get(self, request, org_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        rows = visible_assets(request.user, org).order_by("-created_at")[:200]
        return Response([_asset_payload(a) for a in rows])

    @extend_schema(summary="Start an upload: returns a presigned PUT for this asset only")
    def post(self, request, org_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        if not storage.is_configured():
            return Response({"error": "not_configured", "details": "Media storage is not configured"}, status=501)
        data = request.data or {}
        kind = data.get("kind")
        content_type = str(data.get("content_type") or "")
        if kind not in CONTENT_TYPES or content_type not in CONTENT_TYPES[kind]:
            return invalid("kind and content_type must be an allowed media type")
        try:
            size = int(data.get("size_bytes") or 0)
        except (TypeError, ValueError):
            return invalid("size_bytes must be a number")
        max_bytes = int(getattr(settings, "CONTENT_MAX_UPLOAD_MB", 4096)) * 1024 * 1024
        if size <= 0 or size > max_bytes:
            return invalid(f"size_bytes must be between 1 and {max_bytes}")
        name = str(data.get("name") or "upload").strip()[:200]
        asset = MediaAsset(org=org, uploaded_by=request.user, kind=kind, name=name, content_type=content_type, size_bytes=size)
        asset.storage_key = storage.key_for(org.id, asset.id, f"source-{name}")
        asset.save()
        return Response(
            {**_asset_payload(asset), "upload_url": storage.presign_put(asset.storage_key, content_type), "method": "PUT"},
            status=201,
        )


class AssetDetailView(StudioView):
    @extend_schema(summary="One asset, with a short-lived download URL when ready")
    def get(self, request, org_id, asset_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        asset = visible_assets(request.user, org).filter(pk=asset_id).first()
        return Response(_asset_payload(asset, with_url=True)) if asset else not_found("Asset not found")


class AssetCompleteView(StudioView):
    @extend_schema(summary="Mark an upload complete (the object must exist; length is capped)")
    def post(self, request, org_id, asset_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        asset = MediaAsset.objects.filter(org=org, pk=asset_id, uploaded_by=request.user).first()
        if asset is None:
            return not_found("Asset not found")
        if asset.status == MediaAsset.STATUS_READY:
            return Response(_asset_payload(asset))
        meta = storage.head(asset.storage_key)
        if meta is None:
            return Response({"error": "not_uploaded", "details": "The file is not in storage yet"}, status=409)
        if meta.get("size") is not None and meta["size"] > asset.size_bytes:
            return invalid("the uploaded file is larger than declared")
        data = request.data or {}
        try:
            duration = float(data["duration_seconds"]) if data.get("duration_seconds") is not None else None
            width = int(data["width"]) if data.get("width") is not None else None
            height = int(data["height"]) if data.get("height") is not None else None
        except (TypeError, ValueError):
            return invalid("duration_seconds, width and height must be numbers")
        max_seconds = float(getattr(settings, "CONTENT_MAX_SOURCE_SECONDS", 10800))
        if asset.kind in (MediaAsset.KIND_VIDEO, MediaAsset.KIND_AUDIO) and duration is None:
            return invalid("duration_seconds is required for video and audio")
        if duration is not None and not 0 < duration <= max_seconds:
            return invalid(f"duration must be at most {int(max_seconds)} seconds")
        for v in (width, height):
            if v is not None and not 1 <= v <= 8192:
                return invalid("width and height must be within 1..8192")
        asset.duration_seconds, asset.width, asset.height = duration, width, height
        asset.status = MediaAsset.STATUS_READY
        asset.source_etag = meta.get("etag") or ""
        asset.save(update_fields=["duration_seconds", "width", "height", "status", "source_etag"])
        return Response(_asset_payload(asset))


# --- projects -------------------------------------------------------------------


def _clean_project(user, org, data, partial=False):
    out = {}
    if not partial or "title" in data:
        title = str(data.get("title") or "").strip()
        if not title or len(title) > 200:
            raise ValueError("title is required (at most 200 characters)")
        out["title"] = title
    if "source_assets" in data:
        ids = [_uuid(v) for v in (data.get("source_assets") or [])][:20]
        allowed = visible_assets(user, org).filter(
            pk__in=[i for i in ids if i], status=MediaAsset.STATUS_READY, kind__in=["video", "audio"]
        )
        if None in ids or allowed.count() != len(set(ids)):
            raise ValueError("source_assets must be ready video or audio assets you can see")
        out["source_assets"] = list(allowed)
    if "brand_kit" in data:
        value = data.get("brand_kit")
        out["brand_kit"] = BrandKit.objects.filter(org=org, pk=_uuid(value)).first() if value else None
        if value and out["brand_kit"] is None:
            raise ValueError("brand_kit not found")
    if "template" in data:
        value = data.get("template")
        out["template"] = ContentTemplate.objects.filter(org=org, pk=_uuid(value)).first() if value else None
        if value and out["template"] is None:
            raise ValueError("template not found")
    if "target_platforms" in data:
        platforms = data.get("target_platforms") or []
        if not isinstance(platforms, list) or not set(platforms) <= PLATFORMS:
            raise ValueError(f"target_platforms may contain {', '.join(sorted(PLATFORMS))}")
        out["target_platforms"] = list(dict.fromkeys(platforms))
    return out


def _apply(project, fields):
    assets = fields.pop("source_assets", None)
    for key, value in fields.items():
        setattr(project, key, value)
    project.save()
    if assets is not None:
        project.source_assets.set(assets)


class ProjectListCreateView(StudioView):
    @extend_schema(summary="Content projects you can see")
    def get(self, request, org_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        rows = visible_projects(request.user, org).order_by("-updated_at")[:200]
        return Response([_project_payload(p) for p in rows])

    @extend_schema(summary="Create a content project")
    def post(self, request, org_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        try:
            fields = _clean_project(request.user, org, request.data or {})
        except ValueError as exc:
            return invalid(exc)
        project = ContentProject(org=org, owner=request.user)
        _apply(project, fields)
        return Response(_project_payload(project), status=201)


class ProjectDetailView(StudioView):
    @extend_schema(summary="A content project")
    def get(self, request, org_id, project_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        project = visible_projects(request.user, org).filter(pk=project_id).first()
        return Response(_project_payload(project)) if project else not_found("Project not found")

    @extend_schema(summary="Edit a content project")
    def patch(self, request, org_id, project_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        project = visible_projects(request.user, org).filter(pk=project_id).first()
        if project is None:
            return not_found("Project not found")
        try:
            fields = _clean_project(request.user, org, request.data or {}, partial=True)
        except ValueError as exc:
            return invalid(exc)
        _apply(project, fields)
        return Response(_project_payload(project))

    @extend_schema(summary="Delete a content project")
    def delete(self, request, org_id, project_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        project = visible_projects(request.user, org).filter(pk=project_id).first()
        if project is None:
            return not_found("Project not found")
        project.delete()
        return Response(status=204)



# --- renders (9b) ---------------------------------------------------------------


class ProjectRenderView(StudioView):
    @extend_schema(summary="Queue a render of this project (within the org's monthly quota)")
    def post(self, request, org_id, project_id):
        from content_studio import renders
        from content_studio.models import RenderJob

        org, error = gate(request, self, org_id)
        if error:
            return error
        project = visible_projects(request.user, org).filter(pk=project_id).first()
        if project is None:
            return not_found("Project not found")
        preset = (request.data or {}).get("preset")
        if preset not in RenderJob.PRESETS and not (preset == "custom" and project.template_id):
            return invalid(f"preset must be one of {', '.join(RenderJob.PRESETS)} (or custom with a template)")
        if not project.source_assets.exists() and not project.template_id:
            return invalid("add a source asset or a template first")
        if not storage.is_configured():
            return Response({"error": "not_configured", "details": "Media storage is not configured"}, status=501)
        from billing_v2.entitlements import limit

        quota = limit(org, "renders_per_month", int(getattr(settings, "CONTENT_RENDERS_PER_MONTH", 200)))
        if renders.month_renders(org) >= quota:
            return Response({"error": "quota_exceeded", "details": f"{quota} renders per month"}, status=429)
        changed = renders.changed_sources(project)
        if changed:
            return Response(
                {"error": "source_changed", "details": "A source file changed after upload", "assets": changed}, status=409
            )
        latest = project.edls.order_by("-version").first()
        job = RenderJob.objects.create(
            org=org,
            project=project,
            requested_by=request.user,
            preset=preset,
            edl_version=latest.version if latest else None,
            spec=renders.build_spec(project, preset, latest.version if latest else None, latest.operations if latest else None),
        )
        audit(request.user, "content.render_queue", target=job, payload={"preset": preset}, request=request, org=org)
        return Response(renders.payload(job), status=202)

    @extend_schema(summary="Renders of this project")
    def get(self, request, org_id, project_id):
        from content_studio import renders

        org, error = gate(request, self, org_id)
        if error:
            return error
        project = visible_projects(request.user, org).filter(pk=project_id).first()
        if project is None:
            return not_found("Project not found")
        _demo_tick(org)
        return Response([renders.payload(j, with_url=True) for j in project.renders.order_by("-queued_at")[:50]])


def _demo_tick(org):
    """Demo mode only: the in-process demo worker advances this org's renders."""
    if getattr(settings, "DEMO_MODE", False):
        from workers import demo_render

        demo_render.tick(org)


class RenderListView(StudioView):
    @extend_schema(summary="The render queue: recent renders of projects you can see")
    def get(self, request, org_id):
        from content_studio import renders
        from content_studio.models import RenderJob

        org, error = gate(request, self, org_id)
        if error:
            return error
        _demo_tick(org)
        qs = RenderJob.objects.filter(org=org, project__in=visible_projects(request.user, org)).select_related("project")
        status = request.query_params.get("status")
        if status in ("queued", "running", "succeeded", "failed", "cancelled"):
            qs = qs.filter(status=status)
        rows = qs.order_by("-queued_at")[:100]
        return Response([{**renders.payload(j, with_url=True), "project_title": j.project.title} for j in rows])


def _visible_render(request, org, render_id):
    from content_studio.models import RenderJob

    return RenderJob.objects.filter(org=org, pk=render_id, project__in=visible_projects(request.user, org)).first()


class RenderDetailView(StudioView):
    @extend_schema(summary="Render status, and a short-lived output URL when done")
    def get(self, request, org_id, render_id):
        from content_studio import renders

        org, error = gate(request, self, org_id)
        if error:
            return error
        _demo_tick(org)
        job = _visible_render(request, org, render_id)
        return Response(renders.payload(job, with_url=True)) if job else not_found("Render not found")


class RenderCancelView(StudioView):
    @extend_schema(summary="Cancel a queued or running render")
    def post(self, request, org_id, render_id):
        from content_studio import renders
        from content_studio.models import RenderJob

        org, error = gate(request, self, org_id)
        if error:
            return error
        job = _visible_render(request, org, render_id)
        if job is None:
            return not_found("Render not found")
        updated = RenderJob.objects.filter(
            pk=job.pk, status__in=[RenderJob.STATUS_QUEUED, RenderJob.STATUS_RUNNING]
        ).update(status=RenderJob.STATUS_CANCELLED)
        if not updated:
            return Response({"error": "not_cancellable", "details": "The render already finished"}, status=409)
        job.refresh_from_db()
        return Response(renders.payload(job))


# --- edit decisions, transcripts, captions, AI (9c) ------------------------------


def _project_or_404(request, org, project_id):
    return visible_projects(request.user, org).filter(pk=project_id).first()


def _edl_payload(e):
    if e is None:
        return {"version": 0, "operations": []}
    return {
        "version": e.version,
        "operations": e.operations,
        "created_by_kind": e.created_by_kind,
        "note": e.note,
        "created_at": e.created_at.isoformat(),
    }


class AssetTranscriptView(StudioView):
    @extend_schema(summary="Word timings of an asset")
    def get(self, request, org_id, asset_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        asset = visible_assets(request.user, org).filter(pk=asset_id).first()
        if asset is None:
            return not_found("Asset not found")
        return Response(
            {
                "id": str(asset.id),
                "status": asset.transcript_status or ("done" if asset.transcript_words else ""),
                "duration_seconds": asset.duration_seconds,
                "words": asset.transcript_words or [],
            }
        )

    @extend_schema(summary="Store word timings for an asset (from the transcription pipeline or an upload)")
    def put(self, request, org_id, asset_id):
        from content_studio.edl import EDLInvalid, validate_words

        org, error = gate(request, self, org_id)
        if error:
            return error
        asset = visible_assets(request.user, org).filter(pk=asset_id).first()
        if asset is None:
            return not_found("Asset not found")
        try:
            asset.transcript_words = validate_words((request.data or {}).get("words"), asset.duration_seconds)
        except EDLInvalid as exc:
            return invalid(exc)
        asset.transcript_status = "done" if asset.transcript_words else ""
        asset.save(update_fields=["transcript_words", "transcript_status"])
        return Response({"id": str(asset.id), "words": len(asset.transcript_words)})


class AssetTranscribeView(StudioView):
    throttle_classes = [V2UserThrottle, AISendThrottle]

    @extend_schema(summary="Transcribe an asset with the self-hosted speech-to-text (word timings for the editor)")
    def post(self, request, org_id, asset_id):
        from content_studio import transcribe

        org, error = gate(request, self, org_id)
        if error:
            return error
        asset = visible_assets(request.user, org).filter(pk=asset_id).first()
        if asset is None:
            return not_found("Asset not found")
        if asset.kind not in (MediaAsset.KIND_VIDEO, MediaAsset.KIND_AUDIO) or asset.status != MediaAsset.STATUS_READY:
            return invalid("only ready video or audio can be transcribed")
        data = request.data if isinstance(request.data, dict) else {}
        language = str(data.get("language") or "").lower()[:8]
        if language and not (2 <= len(language) <= 8 and set(language) <= set("abcdefghijklmnopqrstuvwxyz-")):
            return invalid("language must be a language code")
        if asset.transcript_status == "running":
            return Response({"error": "conflict", "details": "Transcription is already running"}, status=409)
        if not transcribe.available():
            return Response({"error": "not_configured", "details": "Speech to text is not configured"}, status=501)
        result = transcribe.start(asset, language or None)
        asset.refresh_from_db()
        audit(request.user, "content.transcribe", target=asset, payload={"demo": result.get("demo", False)}, request=request, org=org)
        return Response({**_asset_payload(asset), "demo": bool(result.get("demo"))}, status=202)


class ProjectEDLView(StudioView):
    @extend_schema(summary="The latest edit decision list (or ?version=)")
    def get(self, request, org_id, project_id):
        org, error = gate(request, self, org_id)
        if error:
            return error
        project = _project_or_404(request, org, project_id)
        if project is None:
            return not_found("Project not found")
        version = request.query_params.get("version")
        edl = project.edls.filter(version=int(version)).first() if version and version.isdigit() else project.edls.order_by("-version").first()
        return Response(_edl_payload(edl))

    @extend_schema(summary="Save a new EDL version (base_version guards concurrent edits)")
    def put(self, request, org_id, project_id):
        from content_studio.edl import EDLInvalid, save_version, validate_operations

        org, error = gate(request, self, org_id)
        if error:
            return error
        project = _project_or_404(request, org, project_id)
        if project is None:
            return not_found("Project not found")
        data = request.data if isinstance(request.data, dict) else {}
        base = data.get("base_version")
        if base is not None and not (isinstance(base, int) and not isinstance(base, bool) and base >= 0):
            return invalid("base_version must be a whole number")
        try:
            ops = validate_operations(project, data.get("operations"))
            edl = save_version(project, ops, request.user, note=str(data.get("note") or ""), base_version=base)
        except EDLInvalid as exc:
            status = 409 if str(exc).startswith("stale") else 400
            return Response({"error": "conflict" if status == 409 else "invalid", "details": str(exc)}, status=status)
        return Response(_edl_payload(edl), status=201)


class ProjectEDLRevertView(StudioView):
    @extend_schema(summary="Undo: copy an earlier version as the newest")
    def post(self, request, org_id, project_id):
        from content_studio.edl import EDLInvalid, save_version, validate_operations

        org, error = gate(request, self, org_id)
        if error:
            return error
        project = _project_or_404(request, org, project_id)
        if project is None:
            return not_found("Project not found")
        try:
            version = int((request.data or {}).get("version"))
        except (TypeError, ValueError):
            return invalid("version must be a number")
        old = project.edls.filter(version=version).first()
        if old is None:
            return not_found("Version not found")
        try:
            # Re-validate: sources may have changed since that version.
            edl = save_version(project, validate_operations(project, old.operations), request.user, note=f"revert to v{old.version}")
        except EDLInvalid as exc:
            return invalid(exc)
        return Response(_edl_payload(edl), status=201)


class ProjectCaptionsView(StudioView):
    @extend_schema(summary="Captions (SRT or VTT) on the edited timeline")
    def get(self, request, org_id, project_id, fmt):
        from django.http import HttpResponse

        from content_studio.edl import captions

        if fmt not in ("srt", "vtt"):
            return not_found("Unknown format")
        org, error = gate(request, self, org_id)
        if error:
            return error
        project = _project_or_404(request, org, project_id)
        if project is None:
            return not_found("Project not found")
        wanted = request.query_params.get("asset")
        asset = (
            project.source_assets.filter(pk=_uuid(wanted)).first() if _uuid(wanted) else None
        ) if wanted else project.source_assets.order_by("created_at").first()
        if asset is None or not asset.transcript_words:
            return Response({"error": "no_transcript", "details": "The asset has no transcript"}, status=409)
        edl = project.edls.order_by("-version").first()
        body = captions(asset, edl.operations if edl else [], fmt)
        response = HttpResponse(body, content_type="text/vtt" if fmt == "vtt" else "application/x-subrip")
        response["Content-Disposition"] = f'attachment; filename="captions.{fmt}"'
        return response


def _ai_asset(request, org, project_id):
    project = _project_or_404(request, org, project_id)
    if project is None:
        return None, None
    asset_id = (request.data or {}).get("asset") if isinstance(request.data, dict) else None
    qs = project.source_assets.filter(kind__in=["video", "audio"])
    if asset_id:
        asset = qs.filter(pk=_uuid(asset_id)).first() if _uuid(asset_id) else None
    else:
        asset = qs.order_by("created_at").first()
    return project, asset


def _clip_payload(r):
    return {
        "id": str(r.id),
        "asset": str(r.asset_id),
        "start": r.start,
        "end": r.end,
        "hook_text": r.hook_text,
        "score": r.score,
        "reason": r.reason,
        "accepted": r.accepted,
    }


class ProjectSuggestClipsView(StudioView):
    throttle_classes = [V2UserThrottle, AISendThrottle]

    def get_throttles(self):
        return [V2UserThrottle()] if self.request.method == "GET" else super().get_throttles()

    @extend_schema(summary="Clip suggestions kept for this project (best first)")
    def get(self, request, org_id, project_id):
        from content_studio.models import ClipSuggestion

        org, error = gate(request, self, org_id)
        if error:
            return error
        project = _project_or_404(request, org, project_id)
        if project is None:
            return not_found("Project not found")
        rows = ClipSuggestion.objects.filter(project=project).order_by("-score")[:50]
        return Response([_clip_payload(r) for r in rows])

    @extend_schema(summary="AI clip suggestions from the transcript (validated, never auto-applied)")
    def post(self, request, org_id, project_id):
        from content_studio import ai
        from content_studio.models import ClipSuggestion

        org, error = gate(request, self, org_id)
        if error:
            return error
        project, asset = _ai_asset(request, org, project_id)
        if project is None or asset is None:
            return not_found("Project or asset not found")
        try:
            clips, rejected = ai.suggest_clips(request.user, org, asset)
        except ai.AIUnavailable as exc:
            return Response({"error": exc.code, "details": "Clip suggestions are not available"}, status=exc.status)
        ClipSuggestion.objects.filter(project=project, asset=asset, accepted=False).delete()
        rows = [ClipSuggestion.objects.create(org=org, project=project, asset=asset, **c) for c in clips]
        return Response({"clips": [_clip_payload(r) for r in rows], "rejected": rejected})


class ProjectAutoEditView(StudioView):
    throttle_classes = [V2UserThrottle, AISendThrottle]

    @extend_schema(summary="AI removes silences, fillers and noise as a new EDL version (undo with revert)")
    def post(self, request, org_id, project_id):
        from content_studio import ai
        from content_studio.edl import EDLInvalid, latest, save_version, validate_operations
        from content_studio.models import EditDecisionList

        org, error = gate(request, self, org_id)
        if error:
            return error
        project, asset = _ai_asset(request, org, project_id)
        if project is None or asset is None:
            return not_found("Project or asset not found")
        try:
            cuts, rejected = ai.suggest_cuts(request.user, org, asset)
        except ai.AIUnavailable as exc:
            return Response({"error": exc.code, "details": "Auto-edit is not available"}, status=exc.status)
        current = latest(project)
        # Replace only earlier AI cuts on this asset; the user's own cuts stay.
        base_ops = [
            o
            for o in (current.operations if current else [])
            if not (o.get("op") == "cut" and o.get("asset") == str(asset.id) and o.get("by") == "ai")
        ]
        try:
            edl = save_version(project, validate_operations(project, base_ops + cuts), request.user, EditDecisionList.BY_AI, "auto-edit")
        except EDLInvalid as exc:
            return invalid(exc)
        return Response({**_edl_payload(edl), "rejected": rejected}, status=201)


class ClipAcceptView(StudioView):
    @extend_schema(summary="Accept a suggested clip: adds a keep range as a new EDL version")
    def post(self, request, org_id, clip_id):
        from content_studio.edl import EDLInvalid, latest, save_version, validate_operations
        from content_studio.models import ClipSuggestion

        org, error = gate(request, self, org_id)
        if error:
            return error
        clip = ClipSuggestion.objects.filter(org=org, pk=clip_id, project__in=visible_projects(request.user, org)).first()
        if clip is None:
            return not_found("Clip not found")
        current = latest(clip.project)
        ops = list(current.operations if current else []) + [
            {"op": "keep", "asset": str(clip.asset_id), "start": clip.start, "end": clip.end}
        ]
        try:
            edl = save_version(clip.project, validate_operations(clip.project, ops), request.user, note="accept clip")
        except EDLInvalid as exc:
            return invalid(exc)
        clip.accepted = True
        clip.save(update_fields=["accepted"])
        return Response(_edl_payload(edl), status=201)


# --- batches, copy, voiceover (9e) -------------------------------------------------


def _clean_row(variables, row, index):
    if not isinstance(row, dict):
        raise ValueError(f"row {index} must be an object")
    extra = set(row) - set(variables)
    if extra:
        raise ValueError(f"row {index} has unknown fields: {', '.join(sorted(extra))}")
    out = {}
    for name, rule in variables.items():
        value = row.get(name)
        if value in (None, ""):
            if rule.get("required"):
                raise ValueError(f"row {index}: {name} is required")
            continue
        if not isinstance(value, str) or len(value) > int(rule.get("maxLength", 500)):
            raise ValueError(f"row {index}: {name} must be text of at most {rule.get('maxLength', 500)} characters")
        out[name] = value
    return out


class BatchRenderView(StudioView):
    @extend_schema(summary="Template + rows: one render per row (e.g. one FLOQ card per question)")
    def post(self, request, org_id):
        from content_studio import renders
        from content_studio.models import RenderJob

        org, error = gate(request, self, org_id)
        if error:
            return error
        if not storage.is_configured():
            return Response({"error": "not_configured", "details": "Media storage is not configured"}, status=501)
        data = request.data or {}
        ensure_builtin_templates(org)
        template = ContentTemplate.objects.filter(org=org, pk=_uuid(data.get("template"))).first()
        if template is None:
            return not_found("Template not found")
        rows = data.get("rows")
        limit = int(getattr(settings, "CONTENT_BATCH_MAX_ROWS", 100))
        if not isinstance(rows, list) or not 1 <= len(rows) <= limit:
            return invalid(f"rows must be a list of 1 to {limit}")
        variables = (template.spec or {}).get("variables") or {}
        try:
            cleaned = [_clean_row(variables, row, i) for i, row in enumerate(rows)]
        except ValueError as exc:
            return invalid(exc)
        from billing_v2.entitlements import limit

        quota = limit(org, "renders_per_month", int(getattr(settings, "CONTENT_RENDERS_PER_MONTH", 200)))
        if renders.month_renders(org) + len(cleaned) > quota:
            return Response({"error": "quota_exceeded", "details": f"{quota} renders per month"}, status=429)
        kit = BrandKit.objects.filter(org=org, pk=_uuid(data.get("brand_kit"))).first() if data.get("brand_kit") else None
        project = ContentProject.objects.create(
            org=org, owner=request.user, title=str(data.get("title") or f"Batch: {template.name}")[:200], template=template, brand_kit=kit
        )
        jobs = [
            RenderJob.objects.create(
                org=org,
                project=project,
                requested_by=request.user,
                preset="custom",
                spec=renders.build_spec(project, "custom", text_fields=row),
            )
            for row in cleaned
        ]
        audit(request.user, "content.batch_queue", target=project, payload={"rows": len(jobs)}, request=request, org=org)
        return Response({"project": str(project.id), "renders": [str(j.id) for j in jobs]}, status=202)


class ProjectCopyView(StudioView):
    throttle_classes = [V2UserThrottle, AISendThrottle]

    @extend_schema(summary="Per-platform titles, descriptions and hashtags (direct only, validated)")
    def post(self, request, org_id, project_id):
        from content_studio import ai, connectors

        org, error = gate(request, self, org_id)
        if error:
            return error
        project = visible_projects(request.user, org).filter(pk=project_id).first()
        if project is None:
            return not_found("Project not found")
        platforms = (request.data or {}).get("platforms") or project.target_platforms or ["youtube"]
        if not isinstance(platforms, list) or not set(platforms) <= PLATFORMS:
            return invalid(f"platforms may contain {', '.join(sorted(PLATFORMS))}")
        asset = project.source_assets.exclude(transcript_words=[]).order_by("created_at").first()
        try:
            copy = ai.platform_copy(request.user, org, project, asset, platforms, connectors)
        except ai.AIUnavailable as exc:
            return Response({"error": exc.code, "details": "Copy is not available"}, status=exc.status)
        return Response({"copy": copy})


AUDIO_EXT = {"audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/ogg": "ogg"}


class VoiceoverView(StudioView):
    throttle_classes = [V2UserThrottle, AISendThrottle]

    @extend_schema(summary="The text-to-speech provider and its voices (501 until one is configured, Q18)")
    def get(self, request, org_id):
        from content_studio.tts import get_tts

        org, error = gate(request, self, org_id)
        if error:
            return error
        provider = get_tts()
        if provider is None:
            return Response({"error": "not_configured", "details": "No text-to-speech provider is configured"}, status=501)
        return Response(provider.info())

    @extend_schema(summary="Script to voiceover: a new audio asset (optionally added to a project)")
    def post(self, request, org_id):
        import io

        from content_studio.tts import MAX_CHARS, TTSError, get_tts

        org, error = gate(request, self, org_id)
        if error:
            return error
        provider = get_tts()
        if provider is None:
            return Response({"error": "not_configured", "details": "No text-to-speech provider is configured"}, status=501)
        if not storage.is_configured():
            return Response({"error": "not_configured", "details": "Media storage is not configured"}, status=501)
        data = request.data if isinstance(request.data, dict) else {}
        text = str(data.get("text") or "").strip()
        if not text or len(text) > MAX_CHARS:
            return invalid(f"text is required (at most {MAX_CHARS} characters)")
        voices = {v.id: v for v in provider.voices()}
        voice_id = str(data.get("voice") or next(iter(voices), ""))
        if voice_id not in voices:
            return invalid("voice must be one of the provider's voices")
        language = str(data.get("language") or voices[voice_id].language).lower()[:8]
        project = None
        if data.get("project"):
            project = visible_projects(request.user, org).filter(pk=_uuid(data.get("project"))).first()
            if project is None:
                return not_found("Project not found")
        try:
            speech = provider.synthesize(text, voice_id, language)
        except TTSError as exc:
            return Response({"error": exc.code, "details": "The voiceover could not be made"}, status=502)
        if speech.content_type not in CONTENT_TYPES["audio"] or not speech.audio:
            return Response({"error": "bad_provider_output", "details": "The voiceover could not be made"}, status=502)
        max_seconds = float(getattr(settings, "CONTENT_MAX_SOURCE_SECONDS", 10800))
        duration = float(speech.duration_seconds or 0)
        if not 0 < duration <= max_seconds:
            return Response({"error": "bad_provider_output", "details": "The voiceover could not be made"}, status=502)
        name = str(data.get("name") or "").strip()[:200] or f"Voiceover: {text[:60]}"
        if provider.is_demo and not name.startswith("Demo"):
            name = f"Demo voiceover: {text[:60]}"[:200]
        asset = MediaAsset(
            org=org,
            uploaded_by=request.user,
            kind=MediaAsset.KIND_AUDIO,
            name=name,
            content_type=speech.content_type,
            size_bytes=len(speech.audio),
            duration_seconds=duration,
            status=MediaAsset.STATUS_READY,
        )
        asset.storage_key = storage.key_for(org.id, asset.id, f"voiceover.{AUDIO_EXT.get(speech.content_type, 'audio')}")
        if not storage.put_file(asset.storage_key, io.BytesIO(speech.audio), speech.content_type):
            return Response({"error": "not_configured", "details": "Media storage is not configured"}, status=501)
        asset.source_etag = (storage.head(asset.storage_key) or {}).get("etag") or ""
        asset.save()
        if project is not None:
            project.source_assets.add(asset)
        audit(
            request.user,
            "content.voiceover",
            target=asset,
            payload={"provider": provider.name, "chars": len(text), "project": str(project.id) if project else None},
            request=request,
            org=org,
        )
        return Response({**_asset_payload(asset, with_url=True), "provider": provider.name, "demo": provider.is_demo}, status=201)
