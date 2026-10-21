"""Data buddy demo data: three datasets built from CSV made here (sign-ups by week and channel,
support tickets, Q4 budget lines), four saved cards and one weekly report with a first run.

The CSV goes through the same reader as an upload, so types are inferred the real way. Numbers are
invented and labelled as demo data. The budget dataset looks like a Google Sheet, but the demo never
fetches it (refreshing says so)."""

import random
from datetime import timedelta

CHANNELS = [("Website", 42), ("Referral", 18), ("Partners", 11), ("Social", 15), ("Events", 6)]
CATEGORIES = ["Login", "Billing", "Bug", "How-to", "Feature request"]
STATUSES = [("Open", 14), ("Pending", 9), ("Solved", 52), ("Closed", 25)]
PRIORITIES = [("Low", 30), ("Normal", 45), ("High", 18), ("Urgent", 7)]
AGENTS = ["Layla", "Youssef", "Sara", "Omar"]
BUDGET = [
    ("Marketing", "Launch ads", 12000, 9400, "Omar"),
    ("Marketing", "Conference booth", 6000, 6650, "Omar"),
    ("Marketing", "Content writers", 3500, 2100, "Sara"),
    ("Engineering", "Cloud hosting", 9000, 7300, "Layla"),
    ("Engineering", "Test devices", 2500, 2900, "Layla"),
    ("Engineering", "Developer tools", 1800, 1200, "Youssef"),
    ("Operations", "Office rent", 15000, 11250, "Nadia"),
    ("Operations", "Internet and phones", 1200, 870, "Nadia"),
    ("People", "Hiring fees", 8000, 3200, "Nadia"),
    ("People", "Team training", 4000, 1500, "Omar"),
    ("Travel", "Client visits", 5000, 4100, "Omar"),
    ("Travel", "Team offsite", 7000, 0, "Nadia"),
]
SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-demo-not-a-real-sheet-000000000000/pub?output=csv"


def _csv(header, rows) -> bytes:
    import csv
    import io

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue().encode()


def _weighted(rng, pairs):
    return rng.choices([p[0] for p in pairs], weights=[p[1] for p in pairs])[0]


def signups_csv(now) -> bytes:
    rng = random.Random(7)
    monday = (now - timedelta(days=now.weekday())).date()
    rows = []
    for back in range(11, -1, -1):
        week = monday - timedelta(weeks=back)
        growth = 1 + (11 - back) * 0.06
        for channel, base in CHANNELS:
            rows.append([week.isoformat(), channel, max(0, int(base * growth + rng.randint(-4, 5)))])
    return _csv(["Week", "Channel", "Signups"], rows)


def tickets_csv(now) -> bytes:
    rng = random.Random(11)
    rows = []
    for n in range(1, 141):
        opened = (now - timedelta(days=rng.randint(0, 80))).date()
        priority = _weighted(rng, PRIORITIES)
        hours = {"Urgent": 1.5, "High": 4, "Normal": 9, "Low": 20}[priority] * rng.uniform(0.5, 1.6)
        rows.append([1000 + n, opened.isoformat(), _weighted(rng, STATUSES), priority, rng.choice(CATEGORIES), round(hours, 1), rng.choice(AGENTS)])
    rows.sort(key=lambda r: r[1])
    return _csv(["Ticket ID", "Opened on", "Status", "Priority", "Category", "First response hours", "Assignee"], rows)


def budget_csv() -> bytes:
    return _csv(["Category", "Line item", "Budgeted", "Spent", "Owner"], [[c, l, f"{b:.2f}", f"{s:.2f}", o] for c, l, b, s, o in BUDGET])


def _dataset(org, owner, name, description, data, **fields):
    from datasets import ingest, services
    from datasets.models import Dataset

    columns, rows = ingest.parse_csv(data)
    ds = Dataset(org=org, owner=owner, name=name, description=description, **fields)
    services.store_rows(ds, columns, rows)
    ds.save()
    return ds


def _card(org, user, ds, title, question, sql):
    from brain.llm.demo_handlers.datasets import chart_and_answer
    from datasets import services
    from datasets.models import SavedQuestion

    result = services.run_sql(ds, sql)
    explained = chart_and_answer({**result, "total_rows": len(result["rows"])}, question)
    card = SavedQuestion(org=org, dataset=ds, created_by=user, title=title, question=question, sql=sql, chart=explained["chart"], answer=explained["answer"])
    services.apply_result(card, result)
    card.save()
    return card


def seed(org, users, now):
    from brain.llm.demo_handlers.datasets import BUDGET as BUDGET_SQL
    from brain.llm.demo_handlers.datasets import SIGNUPS, TICKETS
    from datasets import services
    from datasets.models import Dataset, Report, ReportRun
    from organizations.models import Team
    from rooms.models import Room

    admin, lead = users["admin"], users["lead"]
    eng = Team.objects.filter(org=org, name="Engineering").first()
    signups = _dataset(
        org, admin, "Sign-ups by week and channel", "Weekly sign-ups for the last 12 weeks. Demo data.",
        signups_csv(now), kind=Dataset.KIND_UPLOAD, visibility=Dataset.VISIBILITY_ORG, source_name="signups_by_week.csv",
    )
    tickets = _dataset(
        org, lead, "Support tickets", "Tickets from the help desk export. Demo data.", tickets_csv(now),
        kind=Dataset.KIND_UPLOAD, visibility=Dataset.VISIBILITY_TEAM if eng else Dataset.VISIBILITY_ORG, team=eng,
        source_name="support_tickets.csv",
    )
    budget = _dataset(
        org, admin, "Q4 budget lines", "Budget and spend per line for Q4. Demo data (the sheet is not fetched in the demo).",
        budget_csv(), kind=Dataset.KIND_SHEET, visibility=Dataset.VISIBILITY_ORG, sheet_url=SHEET_URL,
        refresh_every_hours=24, next_refresh_at=now + timedelta(hours=20), source_name="Google Sheet",
    )
    cards = [
        _card(org, admin, signups, "Sign-ups this week vs last", "sign-ups this week vs last", SIGNUPS["vs"]),
        _card(org, admin, signups, "Sign-ups by channel", "sign-ups by channel", SIGNUPS["channel"]),
        _card(org, lead, tickets, "Tickets by status", "tickets by status", TICKETS["status"]),
        _card(org, admin, budget, "Budget left by category", "budget left by category", BUDGET_SQL["left"]),
    ]
    room = Room.objects.filter(org=org, team=eng).first() if eng else None
    report = Report.objects.create(
        org=org, created_by=admin, name="Monday numbers", cadence=Report.CADENCE_WEEKLY, weekday=0, hour=7, room=room,
    )
    report.cards.set([cards[0], cards[2], cards[3]])
    report.recipients.set([lead, users["owner"]])
    report.next_run_at = services.next_run(report, now)
    last = now - timedelta(days=now.weekday() or 7, hours=max(now.hour - 7, 0))
    report.last_run_at, report.last_status = last, "ok"
    report.save()
    ReportRun.objects.create(
        report=report, ran_at=last, status="ok", notified=3, posted_to_room=room is not None,
        results=[{"card": str(c.id), "title": c.title, "headline": services.headline(c), "error": ""} for c in report.cards.all()],
    )
