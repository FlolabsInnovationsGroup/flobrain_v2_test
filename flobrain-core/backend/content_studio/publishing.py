"""Consent checks, approval hashing and publishing (Phase 9d, Decisions 36 and 37)."""

import hashlib
import json
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from content_studio import connectors, storage
from content_studio.models import SCOPES, AssetPerson, ConsentRecord, PublishJob, RenderJob, SocialAccount

logger = logging.getLogger(__name__)
PUBLIC_SCOPE = "public_social"
MAX_ATTEMPTS = 5


def scopes_covering(scope):
    """Scopes that include ``scope`` (marketing ⊇ public_social ⊇ internal)."""
    return list(SCOPES[SCOPES.index(scope):])


def render_assets(render):
    """Every asset that appears in this render's output: its frozen sources and brand media."""
    from content_studio.models import MediaAsset

    spec = render.spec or {}
    ids = [s.get("asset") for s in spec.get("sources", []) if s.get("asset")]
    ids += list((spec.get("brand") or {}).get("asset_ids") or [])
    keys = [s.get("key") for s in spec.get("sources", []) if s.get("key")]
    return MediaAsset.objects.filter(org=render.org).filter(Q(pk__in=ids) | Q(storage_key__in=keys)).distinct()


def _person_key(person):
    return f"u:{person.person_user_id}" if person.person_user_id else f"e:{(person.person_email or '').lower()}:{person.person_name.lower()}"


def has_consent(org, asset, person, scope=PUBLIC_SCOPE, now=None) -> bool:
    """A live consent record covers this tagged person on this asset (or blanket) for ``scope``."""
    if not person.person_user_id and not person.person_email:
        return False
    who = Q(person_user_id=person.person_user_id) if person.person_user_id else Q(person_email__iexact=person.person_email)
    return (
        ConsentRecord.objects.filter(
            who,
            org=org,
            scope__in=scopes_covering(scope),
            revoked_at__isnull=True,
            granted_at__lte=now or timezone.now(),
        )
        .filter(Q(media_asset=asset) | Q(media_asset__isnull=True))
        .exists()
    )


def consent_problems(render, scope=PUBLIC_SCOPE) -> list[dict]:
    """Every person tagged on any asset in the **render** needs live consent for the scope;
    more detected faces than distinct tagged people blocks."""
    problems = []
    now = timezone.now()
    for asset in render_assets(render):
        people = list({_person_key(p): p for p in AssetPerson.objects.filter(asset=asset)}.values())
        if asset.face_count is not None and asset.face_count > len(people):
            problems.append({"asset": str(asset.id), "problem": "untagged_faces", "count": asset.face_count - len(people)})
        for person in people:
            if not has_consent(render.org, asset, person, scope, now):
                problems.append(
                    {
                        "asset": str(asset.id),
                        "problem": "missing_consent",
                        "person": str(person.person_user_id) if person.person_user_id else person.person_name or "unnamed",
                    }
                )
    return problems


def approval_hash(job) -> str:
    body = {
        "render": str(job.render_id),
        "output": job.render.output_key,
        "output_etag": (job.render.output_meta or {}).get("etag", ""),
        "title": job.title,
        "description": job.description,
        "hashtags": job.hashtags,
        "thumbnail": job.thumbnail_key,
        "account": str(job.social_account_id),
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else "",
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def payload(job) -> dict:
    return {
        "id": str(job.id),
        "project": str(job.project_id),
        "render": str(job.render_id),
        "social_account": str(job.social_account_id),
        "platform": job.social_account.platform,
        "title": job.title,
        "description": job.description,
        "hashtags": job.hashtags,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "status": job.status,
        "hash": approval_hash(job),
        "created_at": job.created_at.isoformat(),
        "approved_at": job.approved_at.isoformat() if job.approved_at else None,
        "approved_by": str(job.approved_by_id) if job.approved_by_id else None,
        "external_url": job.external_url or None,
        "visibility": job.visibility or None,
        "error": job.error,
    }


def publish(job_id):
    """Publish one approved job. Re-checks approval hash, consent, account and render first."""
    with transaction.atomic():
        job = (
            PublishJob.objects.select_for_update()
            .select_related("render", "social_account", "project")
            .filter(pk=job_id, status__in=[PublishJob.APPROVED, PublishJob.SCHEDULED])
            .first()
        )
        if job is None:
            return None
        if job.scheduled_at and job.scheduled_at > timezone.now():
            return job
        if job.next_attempt_at and job.next_attempt_at > timezone.now():
            return job
        job.status = PublishJob.PUBLISHING
        job.attempts += 1
        job.save(update_fields=["status", "attempts"])

    def stop(status, error):
        job.status, job.error = status, error[:200]
        job.save(update_fields=["status", "error"])
        if status == PublishJob.FAILED:
            _notify(job, error)
        return job

    if job.approval_hash != approval_hash(job):
        job.approved_by, job.approval_hash = None, ""
        job.save(update_fields=["approved_by", "approval_hash"])
        return stop(PublishJob.AWAITING, "changed_after_approval")
    problems = consent_problems(job.render)
    if problems:
        return stop(PublishJob.AWAITING, "consent_missing")
    meta = storage.head(job.render.output_key)
    if meta is None or (meta.get("etag") or "") != (job.render.output_meta or {}).get("etag", ""):
        job.approved_by, job.approval_hash = None, ""
        job.save(update_fields=["approved_by", "approval_hash"])
        return stop(PublishJob.AWAITING, "output_changed")  # the file is not the one that was approved
    account = job.social_account
    if account.status != SocialAccount.STATUS_CONNECTED:
        return stop(PublishJob.FAILED, "account_not_connected")
    if job.render.status != RenderJob.STATUS_SUCCEEDED:
        return stop(PublishJob.FAILED, "render_not_ready")
    connector = connectors.get(account.platform)
    if connector is None or not connector.configured():
        return stop(PublishJob.FAILED, "connector_not_configured")
    private = account.private_only or connector.unaudited_private
    try:
        result = connector.create_post(
            account.tokens(),
            storage.presign_get(job.render.output_key, expires=3600),
            job.title,
            job.description,
            job.hashtags,
            private,
        )
    except connectors.ConnectorError as exc:
        if exc.transient and job.attempts < MAX_ATTEMPTS:
            job.status = PublishJob.SCHEDULED
            job.next_attempt_at = timezone.now() + timedelta(minutes=2 ** job.attempts)
            job.error = exc.code[:200]
            job.save(update_fields=["status", "next_attempt_at", "error"])
            return job
        return stop(PublishJob.FAILED, exc.code)
    except Exception as exc:  # noqa: BLE001 - recorded, never re-raised into the scheduler
        logger.exception("publish %s failed", job.id)
        return stop(PublishJob.FAILED, type(exc).__name__)
    job.status, job.error = PublishJob.PUBLISHED, ""
    job.external_post_id = str(result.get("id") or "")[:200]
    job.external_url = str(result.get("url") or "")[:200]
    job.visibility = "private" if private else "public"
    job.save(update_fields=["status", "error", "external_post_id", "external_url", "visibility"])
    from organizations.services.core import audit

    audit(job.approved_by or job.created_by, "content.published", target=job, payload={"platform": account.platform}, org=job.org)
    try:
        from platform_api.webhooks import emit

        emit(
            job.org,
            "content.published",
            {
                "publish_job": str(job.id),
                "platform": account.platform,
                "visibility": job.visibility,
                "url": job.external_url if job.visibility == "public" else None,
            },
        )
    except Exception:  # noqa: BLE001 - a webhook problem never undoes a publish
        logger.exception("content.published webhook failed")
    return job


def _notify(job, error):
    try:
        from notifications.services import notify

        notify(
            job.org,
            [job.created_by, job.approved_by],
            "publish_failed",
            {"publish_job": str(job.id), "error": error},
            link=f"studio/{job.project_id}",
            push=True,
        )
    except Exception:  # noqa: BLE001
        logger.exception("could not notify about publish job %s", job.id)


def publish_due(now=None, org=None) -> int:
    """Publish what is due. ``org`` limits it to one org (the demo stands in for the scheduler)."""
    now = now or timezone.now()
    due = PublishJob.objects.filter(status__in=[PublishJob.APPROVED, PublishJob.SCHEDULED])
    if org is not None:
        due = due.filter(org=org)
    due = due.filter(
        Q(scheduled_at__isnull=True) | Q(scheduled_at__lte=now)
    ).filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
    count = 0
    for job_id in due.values_list("id", flat=True)[:100]:
        if publish(job_id):
            count += 1
    return count
