"""Content Studio demo data (``DEMO_MODE`` only; everything is labelled demo).

- Youssef (member) has a project with a spoken demo recording, its word timings and an edit
  (captions on, 9:16), plus a finished 9:16 render from the demo worker.
- Youssef and Sara are tagged in the recording. Youssef consented to public posts; Sara's
  consent was revoked, so publishing that render is blocked until she consents or is untagged.
- A "Sandbox (demo)" social account is connected (posts go to sandbox.invalid only).
- FLOQ question cards: one published last week, one approved and scheduled, so the calendar
  has something on it; a post from Youssef's project waits for approval.
"""

import io
import json
from datetime import timedelta

from django.conf import settings


def _store(key, name, content_type):
    from content_studio import demo_media, storage

    try:
        with open(demo_media.path(name), "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    if not storage.put_file(key, io.BytesIO(data), content_type):
        return None
    return {"size": len(data), "etag": (storage.head(key) or {}).get("etag") or ""}


def _render(org, project, user, preset, now, spec_kwargs=None, minutes_ago=30, gpu=None):
    from content_studio import demo_media, renders
    from content_studio.models import RenderJob
    from workers.demo_render import worker

    latest = project.edls.order_by("-version").first()
    job = RenderJob.objects.create(
        org=org,
        project=project,
        requested_by=user,
        preset=preset,
        edl_version=latest.version if latest else None,
        spec=renders.build_spec(project, preset, latest.version if latest else None, latest.operations if latest else None, **(spec_kwargs or {})),
    )
    name, width, height = demo_media.RENDERS["16x9_1080" if preset == "custom" else preset]
    job.output_key = f"content/{org.id}/renders/{job.id}/output.mp4"
    stored = _store(job.output_key, name, "video/mp4")
    if stored is None:
        job.delete()
        return None
    duration = (demo_media.manifest().get("renders") or {}).get("16x9_1080" if preset == "custom" else preset, {}).get("duration_seconds", 4.0)
    started = now - timedelta(minutes=minutes_ago)
    RenderJob.objects.filter(pk=job.pk).update(
        status=RenderJob.STATUS_SUCCEEDED,
        worker=worker(),
        progress=100,
        gpu_seconds=gpu if gpu is not None else 21.4,
        output_key=job.output_key,
        output_meta={"width": width, "height": height, "duration_seconds": duration, "codec": "h264", "etag": stored["etag"], "demo": True, "sample": name},
        queued_at=started - timedelta(seconds=40),
        started_at=started,
        heartbeat_at=started + timedelta(seconds=50),
        finished_at=started + timedelta(seconds=55),
    )
    job.refresh_from_db()
    return job


def _sandbox_account(org, admin):
    from content_studio.models import SocialAccount
    from integrations import crypto

    if not crypto.is_configured():
        return None  # CREDENTIALS_ENCRYPTION_KEY is needed to store even a sandbox token
    account = SocialAccount(
        org=org,
        platform="sandbox",
        display_name="Sandbox (demo)",
        external_account_id="sb-demo",
        scopes=["post"],
        connected_by=admin,
    )
    account.token_ciphertext = crypto.encrypt(json.dumps({"access_token": "sandbox-token"}), account.id, org.id)
    account.key_version = crypto.current_key_version()
    account.save()
    return account


def seed(org, users, now):
    from content_studio import demo_media, publishing, storage
    from content_studio.edl import validate_words
    from content_studio.models import (
        AssetPerson,
        BrandKit,
        ConsentRecord,
        ContentProject,
        ContentTemplate,
        EditDecisionList,
        MediaAsset,
        PublishJob,
    )
    from content_studio.seeds import ensure_builtin_templates

    if not getattr(settings, "DEMO_MODE", False) or not storage.is_configured():
        return
    member, admin, designer = users["member"], users["admin"], users["designer"]
    kit = BrandKit.objects.filter(org=org).order_by("created_at").first()
    if kit is not None:
        kit.caption_style = {"font": "Cairo", "size": "large", "color": "#FFFFFF", "background": "#0E7C66", "position": "bottom"}
        kit.watermark = {"position": "top_right", "opacity": 0.8}
        kit.save(update_fields=["caption_style", "watermark"])

    # The recording (spoken demo audio with word timings).
    info = demo_media.manifest().get("source") or {}
    asset = MediaAsset(
        org=org,
        uploaded_by=member,
        kind=MediaAsset.KIND_VIDEO,
        name="Launch update recording (demo).mp4",
        content_type="video/mp4",
        status=MediaAsset.STATUS_READY,
        duration_seconds=info.get("duration_seconds") or 39.4,
        width=info.get("width") or 1280,
        height=info.get("height") or 720,
        face_count=2,
        created_at=now - timedelta(days=1),
    )
    asset.storage_key = storage.key_for(org.id, asset.id, "source-launch-update.mp4")
    stored = _store(asset.storage_key, demo_media.SOURCE, "video/mp4")
    if stored is None:
        return
    asset.size_bytes = stored["size"]
    asset.source_etag = stored["etag"]
    asset.transcript_words = validate_words(demo_media.source_words(), asset.duration_seconds)
    asset.transcript_status = "done"
    asset.save()

    # People in it: Youssef consented to public posts; Sara's consent was revoked.
    AssetPerson.objects.create(asset=asset, person_user=member, tagged_by=member)
    AssetPerson.objects.create(asset=asset, person_user=designer, tagged_by=member)
    ConsentRecord.objects.create(
        org=org, person_user=member, person_name=member.username or "", scope="public_social", recorded_by=member, granted_at=now - timedelta(days=20)
    )
    ConsentRecord.objects.create(
        org=org,
        person_user=designer,
        person_name=designer.username or "",
        scope="public_social",
        recorded_by=admin,
        granted_at=now - timedelta(days=20),
        revoked_at=now - timedelta(days=2),
    )

    project = ContentProject.objects.create(
        org=org,
        owner=member,
        title="Launch update shorts (demo)",
        brand_kit=kit,
        target_platforms=["youtube", "linkedin", "tiktok"],
    )
    project.source_assets.set([asset])
    EditDecisionList.objects.create(
        org=org,
        project=project,
        version=1,
        operations=[{"op": "captions", "language": "en", "burn_in": True}, {"op": "reframe", "aspect": "9:16", "mode": "auto"}],
        created_by=member,
        note="captions and 9:16",
    )
    teaser = ContentProject.objects.filter(org=org, title="Launch teaser (30 s)").first()
    if teaser is not None:
        teaser.source_assets.add(asset)
    shorts_render = _render(org, project, member, "9x16_1080", now, minutes_ago=50, gpu=23.8)

    # FLOQ question cards: one published, one scheduled.
    ensure_builtin_templates(org)
    floq = ContentTemplate.objects.filter(org=org, slug="floq-question-card").first()
    cards = ContentProject.objects.create(org=org, owner=admin, title="FLOQ question cards (demo)", template=floq, brand_kit=kit, target_platforms=["linkedin"])
    card_a = _render(org, cards, admin, "custom", now, {"text_fields": {"question": "What would you build with FloBrain?"}}, minutes_ago=60 * 24 * 6, gpu=2.9)
    card_b = _render(org, cards, admin, "custom", now, {"text_fields": {"question": "Which feature should we ship next?"}}, minutes_ago=90, gpu=3.1)

    account = _sandbox_account(org, admin)
    if account is None:
        return
    if card_a is not None:
        job = PublishJob.objects.create(
            org=org, project=cards, render=card_a, social_account=account, created_by=admin,
            title="What would you build with FloBrain?", description="Tell us in the comments. (Demo post)", hashtags=["FLOQ", "NileLabs"],
            scheduled_at=now - timedelta(days=5, hours=3),
        )
        PublishJob.objects.filter(pk=job.pk).update(
            status=PublishJob.PUBLISHED, approved_by=users["owner"], approved_at=now - timedelta(days=6),
            approval_hash=publishing.approval_hash(job), external_post_id="sb-demo-1",
            external_url="https://sandbox.invalid/post/sb-demo-1", visibility="public",
            metrics={"views": 1240, "likes": 87, "comments": 12, "demo": True}, attempts=1,
        )
    if card_b is not None:
        job = PublishJob.objects.create(
            org=org, project=cards, render=card_b, social_account=account, created_by=admin,
            title="Which feature should we ship next?", description="Vote in the comments. (Demo post)", hashtags=["FLOQ"],
            scheduled_at=(now + timedelta(days=3)).replace(hour=9, minute=0, second=0, microsecond=0),
        )
        PublishJob.objects.filter(pk=job.pk).update(
            status=PublishJob.SCHEDULED, approved_by=users["owner"], approved_at=now - timedelta(hours=1), approval_hash=publishing.approval_hash(job)
        )
    if shorts_render is not None:
        PublishJob.objects.create(
            org=org, project=project, render=shorts_render, social_account=account, created_by=member,
            title="We launch next month", description="The Nile Labs app launches in English and Arabic. (Demo post)",
            hashtags=["launch", "NileLabs"], scheduled_at=(now + timedelta(days=7)).replace(hour=10, minute=0, second=0, microsecond=0),
        )
