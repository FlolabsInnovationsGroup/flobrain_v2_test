"""Imports demo data: one finished import of the bundled Notion export (fake pages) into the
Design room, so the Import page has history with undo. The bundled Slack export (fake people,
3 channels, 150 messages) stays ready to try from the page ("Try the sample Slack export").
Everything comes from ``imports/fixtures``; nothing reaches the network."""

import logging
from datetime import timedelta

logger = logging.getLogger(__name__)


def seed(org, users, now):
    from imports import services
    from imports.models import ImportRun
    from organizations.models import Team
    from rooms.models import Room

    team = Team.objects.filter(org=org, name="Design").first()
    room = Room.objects.filter(org=org, team=team, kind=Room.KIND_TEAM).first() if team else None
    admin = users.get("admin")
    if room is None or admin is None:
        return
    folder, name = services.SAMPLES["notion"]
    run = ImportRun.objects.create(
        org=org, source=ImportRun.SOURCE_NOTION_ZIP, created_by=admin, label=name, is_demo=True,
        files=[{"key": services.FIXTURE_PREFIX + folder, "name": name, "size": len(services.fixture_zip(folder).getvalue())}],
    )
    try:
        services.analyze(run)
        run.refresh_from_db()
        refs = [i["ref"] for i in (run.preview or {}).get("items") or [] if i.get("supported")]
        ImportRun.objects.filter(pk=run.pk).update(mapping={"room_id": str(room.id), "refs": refs}, status=ImportRun.QUEUED)
        services.execute(run.pk)
    except Exception:  # noqa: BLE001 - demo data must never break the demo reset
        logger.exception("imports demo seed failed")
        return
    started = now - timedelta(days=2, hours=3)
    ImportRun.objects.filter(pk=run.pk).update(created_at=started, started_at=started, finished_at=started + timedelta(seconds=4))
