"""Rooms in the demo: mentions, a second DM, announcements, unread markers and room AI threads.

Every answer in the seeded AI threads is labelled as coming from the demo model. Live translation
of these messages is answered by ``brain/llm/demo_handlers/rooms.py``.
"""

from datetime import timedelta

DEMO_NOTE = "(Answer from FloBrain's demo model: it quotes the closest source. A real model would write a full answer.)"


def seed(org, users, now):
    from brain.models import Chat, Message
    from docs_app.models import Document
    from notifications.services import notify
    from rooms.models import Announcement, Room, RoomMember, RoomMessage
    from rooms.services import pair_key_for

    lead, member, designer, admin = users["lead"], users["member"], users["designer"], users["admin"]
    eng = Room.objects.filter(org=org, kind=Room.KIND_TEAM, team__name="Engineering").first()
    design = Room.objects.filter(org=org, kind=Room.KIND_TEAM, team__name="Design").first()
    project = Room.objects.filter(org=org, kind=Room.KIND_PROJECT).first()
    if eng is None or project is None or design is None:
        return

    def say(room, who, body, minutes_ago):
        return RoomMessage.objects.create(room=room, author=who, body=body, created_at=now - timedelta(minutes=minutes_ago))

    # Mentions (with their notifications, as posting them through the API would create).
    mention_project = say(project, lead, "@Youssef Adel can you check the crash reporting setup before Friday?", 45)
    say(project, member, "تمام، سأراجعه اليوم.", 40)
    mention_eng = say(eng, member, "@Layla the push notifications API is ready for review.", 20)
    say(eng, lead, "Thanks! I'll review it after lunch.", 15)
    say(eng, member, "النسخة التجريبية جاهزة للاختبار على أندرويد.", 10)
    notify(org, [member], "mention", {"room": str(project.id), "message": str(mention_project.id), "by": lead.username,
                                      "room_name": project.name, "text": f"{lead.username} mentioned you"}, link=f"rooms/{project.id}")
    notify(org, [lead], "mention", {"room": str(eng.id), "message": str(mention_eng.id), "by": member.username,
                                    "room_name": eng.name, "text": f"{member.username} mentioned you"}, link=f"rooms/{eng.id}")

    # A second direct message: Sara and Youssef.
    dm = Room.objects.create(org=org, name="Sara / Youssef", kind=Room.KIND_DIRECT, pair_key=pair_key_for(designer, member))
    for who in (designer, member):
        RoomMember.objects.create(room=dm, user=who)
    dm_mention = say(dm, designer, "Here are the final onboarding illustrations. @Youssef can you add them to the build?", 35)
    say(dm, member, "سأضيفها اليوم، شكرًا يا سارة.", 30)
    notify(org, [member], "mention", {"room": str(dm.id), "message": str(dm_mention.id), "by": designer.username,
                                      "room_name": dm.name, "text": f"{designer.username} mentioned you"}, link=f"rooms/{dm.id}")

    # Announcements: one pinned in Engineering, one already unpinned in the project room.
    Announcement.objects.create(
        org=org, room=eng, body="Code review within one working day. Tag the reviewer with @ in this room.", created_by=lead,
        created_at=now - timedelta(days=2),
    )
    Announcement.objects.create(
        org=org, room=project, body="Design review moved to Wednesday 14:00.", created_by=admin, pinned=False,
        created_at=now - timedelta(days=6),
    )

    # Read markers: Youssef has read Engineering up to an hour ago, so newer messages show as unread.
    RoomMember.objects.filter(room=eng, user=member).update(last_read_at=now - timedelta(minutes=60))
    RoomMember.objects.filter(room=project, user=member).update(last_read_at=now - timedelta(minutes=100))

    # Room AI threads (private to each person), answered by the demo model with citations.
    plan = Document.objects.filter(org=org, room=project, title="Launch plan").first()
    device = RoomMessage.objects.filter(room=eng, body__startswith="Omar is ordering one").first()

    def thread(who, room, title, question, answer, sources, minutes_ago):
        chat = Chat.objects.create(user=who, org=org, room=room, title=title)
        at = now - timedelta(minutes=minutes_ago)
        Message.objects.create(chat=chat, role=Message.ROLE_USER, text=question, created_at=at)
        Message.objects.create(chat=chat, role=Message.ROLE_ASSISTANT, text=answer, sources=sources or None,
                               created_at=at + timedelta(seconds=3))
        Chat.objects.filter(pk=chat.pk).update(updated_at=at + timedelta(seconds=3))

    if plan is not None:
        thread(
            member, project, "When is the code freeze?", "When is the code freeze?",
            f"In “Launch plan” [1]: “Code freeze Friday.”\n\n{DEMO_NOTE}",
            [{"n": 1, "source_type": "doc", "source_id": str(plan.id), "room": str(project.id), "title": plan.title,
              "score": 0.91, "excerpt": plan.content_text[:300]}],
            50,
        )
    if device is not None:
        thread(
            member, eng, "Android test device", "What did we decide about the Android test device?",
            f"In “Message in {eng.name}” [1]: “{device.body}”\n\n{DEMO_NOTE}",
            [{"n": 1, "source_type": "room_message", "source_id": str(device.id), "room": str(eng.id),
              "title": f"Message in {eng.name}", "score": 0.88, "excerpt": device.body[:300]}],
            25,
        )
        thread(
            lead, eng, "Blocked work this week", "What is blocking the team this week?",
            f"In “Message in {eng.name}” [1]: “{device.body}”\n\n{DEMO_NOTE}",
            [{"n": 1, "source_type": "room_message", "source_id": str(device.id), "room": str(eng.id),
              "title": f"Message in {eng.name}", "score": 0.84, "excerpt": device.body[:300]}],
            70,
        )
