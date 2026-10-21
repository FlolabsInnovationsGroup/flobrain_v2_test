"""Demo data for docs, learning and integrations (all labelled demo):

- "Launch plan" gets a three-version history and a small attachment (local storage).
- Learning progress for the "Autumn interns" cohort and Youssef's mentorship.
- A Notion masterclass database (demo connection, canned pages, Team audience property).
- The seeded GitHub connection becomes a demo connection, so "Sync now" works without a token.
- The demo signing key and one issued certificate (Sara's internship), "Signed with a demo key".
Demo connections never call the network; outside demo mode they do nothing.
"""

from datetime import timedelta

DEMO_DB = "0d3e0000-0000-4000-8000-000000000001"


def _docs(org, users, now):
    from docs_app.models import Document, DocumentRevision, StoredFile
    from docs_app.views import _blob_path, storage_mode

    plan = Document.objects.filter(org=org, title="Launch plan").first()
    if plan is None:
        return
    v1 = plan.content_text
    v2 = v1.replace("3. Blog post and social posts on launch day.", "3. Blog post and social posts on launch day.\n4. Release notes in Arabic and English.")
    v3 = v2.replace("Risks: Android login timeout, store review delays.", "Risks: Android login timeout (test device ordered), store review delays.")
    for version, text, who, ago in ((2, v2, users["member"], 26), (3, v3, users["lead"], 3)):
        DocumentRevision.objects.update_or_create(
            document=plan, version=version, defaults={"content_text": text, "created_by": who, "created_at": now - timedelta(hours=ago)}
        )
    Document.objects.filter(pk=plan.pk).update(content_text=v3, version=3, updated_by=users["lead"])
    if storage_mode() != "local":
        return
    body = b"Demo attachment\n\nLaunch checklist\n- Code freeze Friday\n- Store screenshots\n- Blog post draft\n"
    stored = StoredFile.objects.create(
        org=org, room=plan.room, document=plan, name="launch-checklist.txt", content_type="text/plain",
        status=StoredFile.STATUS_READY, created_by=users["admin"], size_bytes=len(body),
    )
    path = _blob_path(stored)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        StoredFile.objects.filter(pk=stored.pk).update(local_path=f"{org.id}/{stored.id}")
    except OSError:
        stored.delete()


def _progress(org, users, now):
    from learning.models import LearningPath, PathProgress, Quiz, QuizAttempt

    path = LearningPath.objects.filter(org=org).first()
    quiz = Quiz.objects.filter(org=org, status=Quiz.PUBLISHED).first()
    if quiz is not None:
        QuizAttempt.objects.create(org=org, quiz=quiz, user=users["member"], answers=[1, 0], score=100, passed=True, created_at=now - timedelta(days=2))
        QuizAttempt.objects.create(org=org, quiz=quiz, user=users["designer"], answers=[0, 0], score=50, passed=False, created_at=now - timedelta(days=1))
    if path is not None:
        PathProgress.objects.update_or_create(path=path, user=users["member"], defaults={"done_steps": [0, 1, 2], "completed_at": now - timedelta(days=2)})
        PathProgress.objects.update_or_create(path=path, user=users["designer"], defaults={"done_steps": [0]})


def _connections(org, users, now):
    from connectors import sdk
    from connectors.catalog import notion  # noqa: F401  (registers the connector)
    from connectors.models import Connection, ExternalItem
    from rooms.models import Room

    Connection.objects.filter(org=org, connector="github").update(
        config={"repo": "nile-labs/mobile-app", "demo": True}, last_error="", last_sync_at=now - timedelta(hours=5)
    )
    room = Room.objects.filter(org=org, kind=Room.KIND_PROJECT).order_by("created_at").first()
    if room is None:
        return
    conn = Connection.objects.create(
        org=org, connector="notion", label="Notion masterclasses (demo)", room=room, created_by=users["admin"], last_sync_at=now - timedelta(hours=1),
        config={"database_id": DEMO_DB, "audience_property": "Team", "status_property": "Status", "database_title": "Masterclasses (demo)", "demo": True},
    )
    for item in sdk.get("notion").demo_items(conn):
        ExternalItem.objects.create(
            org=org, connection=conn, kind=item["kind"], external_id=item["external_id"], title=item["title"], url=item["url"],
            state=item["state"], meta=item["meta"], external_updated_at=now - timedelta(days=3),
        )


def _certificate(org, users, now):
    from learning import certs
    from learning.models import Certificate

    try:
        if certs.using_demo_key():
            certs.store_demo_key(org)
        if Certificate.objects.filter(org=org, user=users["designer"]).exists():
            return
        data = certs.build_data(org, users["designer"], "internship_completion")
        data["issued_at"] = now.date().isoformat()
        Certificate.objects.create(
            org=org, user=users["designer"], kind="internship_completion", data=data, signature=certs.sign(data), key_id=certs.key_id(),
            issued_by=users["admin"], public_slug="demo-sara-internship",
        )
    except certs.NotConfigured:
        pass  # outside demo mode without a signing key: no certificate


def seed(org, users, now):
    _docs(org, users, now)
    _progress(org, users, now)
    _connections(org, users, now)
    _certificate(org, users, now)
