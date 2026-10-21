"""Channels demo: a WhatsApp number, a Telegram bot and a website chat (all simulated, labelled demo),
two documents marked public for customers, a support room for hand-offs, Youssef's Telegram linked
to his buddy, and six customer conversations in mixed states. Nothing here calls a provider."""

from datetime import timedelta


def seed(org, users, now):
    from channels.models import (
        ChannelConnection,
        ChannelLink,
        CustomerConversation,
        CustomerKnowledge,
        CustomerMessage,
        CustomerSettings,
    )
    from docs_app.models import Document, DocumentRevision
    from rooms.models import Room, RoomMember, RoomMessage

    admin, lead, member = users["admin"], users["lead"], users["member"]

    support = Room.objects.create(org=org, name="Customer support", kind=Room.KIND_GROUP)
    for who in (admin, lead, member):
        RoomMember.objects.create(room=support, user=who)
    RoomMessage.objects.create(
        room=support, author=admin, body="Customer hand-offs from the website chat and WhatsApp land here. Reply from Customers.",
        created_at=now - timedelta(days=2),
    )

    pricing = Document.objects.create(
        org=org, room=support, title="Plans and pricing (public)", created_by=admin,
        content_text=(
            "# Plans and pricing\n\nThe Starter plan costs 8 USD per person per month and includes buddies and rooms.\n\n"
            "The Team plan costs 19 USD per person per month and adds Content Studio and integrations.\n\n"
            "Every plan has a 14 day free trial. You can cancel any time from Settings, Billing.\n\n"
            "We accept cards and bank transfer. Invoices are sent by email on the first day of each month."
        ),
    )
    delivery = Document.objects.create(
        org=org, room=support, title="Setup, support hours and languages (public)", created_by=admin,
        content_text=(
            "# Setup and support\n\nSetup takes about one day. Our team imports your rooms and documents for you.\n\n"
            "Support hours are Sunday to Thursday, 9:00 to 18:00 Cairo time. Urgent issues get an answer within 4 hours.\n\n"
            "The app works in Arabic, English, Turkish, French and Portuguese, on the web and on phones."
        ),
    )
    for doc in (pricing, delivery):
        DocumentRevision.objects.create(document=doc, version=1, content_text=doc.content_text, created_by=admin)
        CustomerKnowledge.objects.create(org=org, document=doc, added_by=admin)
    CustomerSettings.objects.create(
        org=org, auto_reply=False, escalation_room=support, blocked_topics=["refund", "lawyer", "contract change"],
        buddy_name="Nile Labs helper", greeting="Hi! I'm the Nile Labs helper. Ask me about plans, setup or support.", updated_by=admin,
    )

    wa = ChannelConnection.objects.create(
        org=org, kind=ChannelConnection.WHATSAPP, label="WhatsApp (demo)", status=ChannelConnection.ACTIVE, demo=True,
        config={"phone_number_id": "100000000000001", "waba_id": "200000000000002", "display_phone": "+20 100 000 0001"},
        serve_team=True, serve_customers=True, created_by=admin, last_checked_at=now - timedelta(hours=3),
    )
    tg = ChannelConnection.objects.create(
        org=org, kind=ChannelConnection.TELEGRAM, label="Telegram (demo)", status=ChannelConnection.ACTIVE, demo=True,
        config={"bot_username": "nile_labs_demo_bot"}, serve_team=True, serve_customers=True, created_by=admin,
        last_checked_at=now - timedelta(hours=3),
    )
    web = ChannelConnection.objects.create(
        org=org, kind=ChannelConnection.WEBSITE, label="Website chat (demo)", status=ChannelConnection.ACTIVE, demo=True,
        site_key="demo-nile-labs", config={"allowed_origins": ["https://nile-labs.example", "http://localhost:3000"]},
        serve_team=False, serve_customers=True, created_by=admin,
    )
    ChannelLink.objects.create(
        org=org, user=member, connection=tg, status=ChannelLink.ACTIVE, external_id="555000111", external_name="Youssef",
        linked_at=now - timedelta(days=1),
    )

    def conversation(conn, name, contact, status, minutes_ago, *, mode="buddy", reason="", room=None, assignee=None, external=""):
        return CustomerConversation.objects.create(
            org=org, connection=conn, channel=conn.kind, customer_name=name, contact_masked=contact, status=status, mode=mode,
            escalation_reason=reason, assigned_room=room, assignee=assignee, demo=True, external_id=external,
            last_customer_at=now - timedelta(minutes=minutes_ago), last_message_at=now - timedelta(minutes=minutes_ago - 1),
            created_at=now - timedelta(minutes=minutes_ago + 5),
        )

    def say(conv, role, text, minutes_ago, status="sent", author=None, approved_by=None, citations=None):
        CustomerMessage.objects.create(
            conversation=conv, role=role, text=text, status=status, author=author, approved_by=approved_by,
            citations=citations or [], created_at=now - timedelta(minutes=minutes_ago),
        )

    def cite(doc, n=1):
        return [{"n": n, "document": str(doc.id), "title": doc.title, "excerpt": doc.content_text[:200]}]

    c1 = conversation(wa, "Mona Fathy", "+20 •••• 4417", CustomerConversation.OPEN, 180, external="201001234417")
    say(c1, "customer", "Hi, how much is the Team plan?", 180)
    say(c1, "buddy", "The Team plan costs 19 USD per person per month and adds Content Studio and integrations. [1] (Demo answer)", 178,
        approved_by=admin, citations=cite(pricing))
    say(c1, "customer", "Great, thanks!", 170)

    c2 = conversation(wa, "Karim Saleh", "+20 •••• 9032", CustomerConversation.OPEN, 12, external="201229909032")
    say(c2, "customer", "Is there a free trial before we pay?", 12)
    say(c2, "buddy", "Yes. Every plan has a 14 day free trial, and you can cancel any time from Settings, Billing. [1] (Demo answer)", 11,
        status="draft", citations=cite(pricing))

    c3 = conversation(web, "Website visitor 4821", "", CustomerConversation.WAITING_HUMAN, 35, mode="human", reason="asked_for_human", room=support)
    say(c3, "customer", "Can I talk to a real person about a custom setup for 200 people?", 35)
    say(c3, "system", "Thanks. I'm passing you to a person on our team. They'll reply here soon.", 34)

    c4 = conversation(tg, "Hana Ali", "Chat •••872", CustomerConversation.RESOLVED, 60 * 26, room=support, assignee=lead, external="777000872")
    say(c4, "customer", "Do you support Turkish?", 60 * 26)
    say(c4, "staff", "Yes, the app works in Turkish, and in Arabic, English, French and Portuguese.", 60 * 26 - 20, author=lead)
    say(c4, "customer", "Perfect, thank you.", 60 * 26 - 25)

    c5 = conversation(web, "Ahmed (Cairo Bikes)", "", CustomerConversation.OPEN, 6)
    say(c5, "customer", "What are your support hours?", 6)
    say(c5, "buddy", "Support hours are Sunday to Thursday, 9:00 to 18:00 Cairo time. [1] (Demo answer)", 5, status="draft", citations=cite(delivery))

    c6 = conversation(wa, "Salma Mostafa", "+20 •••• 1188", CustomerConversation.WAITING_HUMAN, 50, mode="human", reason="blocked_topic",
                      room=support, assignee=member, external="201551181188")
    say(c6, "customer", "I want a refund for last month, we didn't use it.", 50)
    say(c6, "system", "Thanks. I'm passing you to a person on our team. They'll reply here soon.", 49)
    say(c6, "staff", "Hi Salma, I'm Youssef. I'm checking your invoice now and will reply within the hour.", 40, author=member)
    RoomMessage.objects.create(
        room=support, author=admin, body="Customer buddy: Salma Mostafa on WhatsApp needs a person (the message is about a topic the buddy must not answer). Open Customers to reply.",
        created_at=now - timedelta(minutes=49),
    )
    RoomMessage.objects.create(
        room=support, author=admin, body="Customer buddy: Website visitor 4821 on Website chat needs a person (the customer asked for a person). Open Customers to reply.",
        created_at=now - timedelta(minutes=34),
    )
