"""Google Workspace: Gmail send and draft, Calendar event, Docs, Sheets append, Drive upload."""

import base64
import secrets
import urllib.parse
from email.message import EmailMessage
from email.policy import SMTP

from django.utils.dateparse import parse_datetime

from integrations.write.registry import (
    EMAILS,
    HIGH,
    MEDIUM,
    Action,
    Provider,
    obj,
    recipients,
    register,
    short,
    single_line,
    text,
)

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CAL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
DOCS = "https://docs.googleapis.com/v1/documents"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
SPREADSHEET_ID = r"^[A-Za-z0-9_-]{20,100}$"
FOLDER_ID = r"^[A-Za-z0-9_-]{10,100}$"
TEXT_TYPES = ["text/plain", "text/markdown", "text/csv", "text/html"]

MAIL_SCHEMA = obj(
    {"to": EMAILS, "cc": EMAILS, "subject": text(200, 1), "body": text(20000, 1)},
    ["to", "subject", "body"],
)


def _mail_checks(args, need_to=True):
    if need_to and not args.get("to"):
        raise ValueError("add at least one recipient")
    single_line(args.get("subject", ""), "subject")


def _raw(args) -> str:
    msg = EmailMessage(policy=SMTP)
    if args.get("to"):
        msg["To"] = ", ".join(args["to"])
    if args.get("cc"):
        msg["Cc"] = ", ".join(args["cc"])
    msg["Subject"] = args.get("subject", "")
    msg.set_content(args["body"])
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def _send_preview(args, conn=None):
    cc = f" (cc {recipients(args['cc'])})" if args.get("cc") else ""
    return f"Send email to {recipients(args['to'])}{cc}: Subject “{short(args['subject'], 90)}”"


def _send(client, args, conn):
    data = client.call("POST", f"{GMAIL}/messages/send", json_body={"raw": _raw(args)})
    mid = str(data.get("id") or "")
    return {"id": mid, "url": f"https://mail.google.com/mail/u/0/#all/{urllib.parse.quote(mid)}" if mid else "", "title": args["subject"]}


def _draft_preview(args, conn=None):
    to = recipients(args["to"]) if args.get("to") else "no one yet"
    return f"Save a Gmail draft to {to}: Subject “{short(args['subject'], 90)}” (not sent)"


def _draft(client, args, conn):
    data = client.call("POST", f"{GMAIL}/drafts", json_body={"message": {"raw": _raw(args)}})
    return {"id": str(data.get("id") or ""), "url": "https://mail.google.com/mail/u/0/#drafts", "title": args["subject"]}


EVENT_SCHEMA = obj(
    {
        "title": text(200, 1),
        "starts_at": {"type": "string", "format": "date-time"},
        "ends_at": {"type": "string", "format": "date-time"},
        "description": text(8000),
        "location": text(200),
        "attendees": EMAILS,
        "notify_attendees": {"type": "boolean"},
    },
    ["title", "starts_at", "ends_at"],
)


def event_checks(args):
    single_line(args.get("title", ""), "title")
    starts, ends = parse_datetime(args["starts_at"]), parse_datetime(args["ends_at"])
    if starts.tzinfo is None or ends.tzinfo is None:
        raise ValueError("starts_at and ends_at need a time zone, like 2026-10-22T14:00:00+02:00")
    if ends <= starts:
        raise ValueError("ends_at must be after starts_at")


def event_preview(product, args):
    starts = parse_datetime(args["starts_at"])
    when = starts.strftime("%a %d %b %Y %H:%M") + (f" {starts.tzname()}" if starts.tzname() else "")
    guests = args.get("attendees") or []
    tail = ""
    if guests:
        tail = f", with {recipients(guests)}" + (" (invites sent)" if args.get("notify_attendees", product == "Outlook") else " (no invites sent)")
    return f"Create {product} event “{short(args['title'], 80)}” on {when}{tail}"


def _event(client, args, conn):
    body = {
        "summary": args["title"],
        "description": args.get("description", ""),
        "location": args.get("location", ""),
        "start": {"dateTime": args["starts_at"]},
        "end": {"dateTime": args["ends_at"]},
        "attendees": [{"email": e} for e in args.get("attendees") or []],
    }
    notify = "all" if args.get("notify_attendees") else "none"
    data = client.call("POST", f"{CAL}?sendUpdates={notify}", json_body=body)
    return {"id": str(data.get("id") or ""), "url": _https(data.get("htmlLink")), "title": args["title"]}


def _doc(client, args, conn):
    data = client.call("POST", DOCS, json_body={"title": args["title"]})
    doc_id = str(data.get("documentId") or "")
    if not doc_id:
        raise ValueError("Google did not return a document id")
    if args.get("body"):
        client.call(
            "POST",
            f"{DOCS}/{urllib.parse.quote(doc_id)}:batchUpdate",
            json_body={"requests": [{"insertText": {"location": {"index": 1}, "text": args["body"]}}]},
        )
    return {"id": doc_id, "url": f"https://docs.google.com/document/d/{urllib.parse.quote(doc_id)}/edit", "title": args["title"]}


ROWS = {"type": "array", "maxItems": 500, "items": {"type": "array", "maxItems": 50, "items": text(5000)}}
SHEETS_SCHEMA = obj(
    {"spreadsheet_id": text(100, 20), "sheet": text(100), "rows": ROWS, "spreadsheet_name": text(120)},
    ["spreadsheet_id", "rows"],
)


def _sheet_checks(args):
    import re

    if not re.match(SPREADSHEET_ID, args["spreadsheet_id"]):
        raise ValueError("spreadsheet_id is not a Google Sheets id")
    if not args["rows"]:
        raise ValueError("add at least one row")
    single_line(args.get("sheet", ""), "sheet")


def _sheet_preview(args, conn=None):
    n = len(args["rows"])
    name = args.get("spreadsheet_name") or args["spreadsheet_id"][:12] + "…"
    tab = f" ({args['sheet']})" if args.get("sheet") else ""
    return f"Append {n} row{'s' if n != 1 else ''} to Google Sheet “{short(name, 60)}”{tab}"


def _sheet(client, args, conn):
    sheet = (args.get("sheet") or "Sheet1").replace("'", "''")
    cell = urllib.parse.quote(f"'{sheet}'!A1", safe="")
    sid = urllib.parse.quote(args["spreadsheet_id"])
    # RAW, not USER_ENTERED: a value that starts with "=" stays text and never becomes a formula.
    url = f"{SHEETS}/{sid}/values/{cell}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS"
    data = client.call("POST", url, json_body={"values": args["rows"]})
    updated = (data.get("updates") or {}).get("updatedRange", "") if isinstance(data, dict) else ""
    return {"id": str(updated), "url": f"https://docs.google.com/spreadsheets/d/{sid}/edit", "title": args.get("spreadsheet_name") or "Google Sheet"}


UPLOAD_SCHEMA = obj(
    {"name": text(200, 1), "content": text(200000, 1), "mime_type": {"type": "string", "enum": TEXT_TYPES}, "folder_id": text(100)},
    ["name", "content"],
)


def file_checks(args):
    import re

    name = args["name"]
    single_line(name, "name")
    if "/" in name or "\\" in name or name in (".", ".."):
        raise ValueError("name must be a file name without folders")
    if args.get("folder_id") and not re.match(FOLDER_ID, args["folder_id"]):
        raise ValueError("folder_id is not a Drive folder id")


def size_label(content: str) -> str:
    size = len(content.encode("utf-8"))
    return f"{size} bytes" if size < 1024 else f"{round(size / 1024)} KB"


def _upload(client, args, conn):
    import json

    boundary = "flobrain-" + secrets.token_hex(12)
    meta = {"name": args["name"]}
    if args.get("folder_id"):
        meta["parents"] = [args["folder_id"]]
    mime = args.get("mime_type") or "text/plain"
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
        f"--{boundary}\r\nContent-Type: {mime}; charset=UTF-8\r\n\r\n{args['content']}\r\n--{boundary}--\r\n"
    ).encode("utf-8")
    data = client.call(
        "POST",
        f"{UPLOAD}?uploadType=multipart&fields=id,name,webViewLink",
        body=body,
        content_type=f"multipart/related; boundary={boundary}",
    )
    fid = str(data.get("id") or "")
    url = _https(data.get("webViewLink")) or (f"https://drive.google.com/file/d/{urllib.parse.quote(fid)}/view" if fid else "")
    return {"id": fid, "url": url, "title": args["name"]}


def _https(value) -> str:
    return value if isinstance(value, str) and value.startswith("https://") else ""


def _identify(client, token):
    data = client.call("GET", "https://www.googleapis.com/oauth2/v3/userinfo")
    email = str(data.get("email") or "") if isinstance(data, dict) else ""
    return (email or "Google account"), {}


def _demo(kind):
    def make(args):
        n = secrets.token_hex(4)
        title = args.get("subject") or args.get("title") or args.get("name") or args.get("spreadsheet_name") or "Google Sheet"
        return {"id": f"demo-{n}", "url": f"https://workspace.example.com/{kind}/{n}", "title": title}

    return make


register(
    Provider(
        key="google_workspace",
        name="Google Workspace",
        description="Send and draft Gmail, add Calendar events, create Docs, append to Sheets, upload to Drive.",
        per_user=True,
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        base_scopes=("openid", "email"),
        auth_params={"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"},
        hosts=frozenset(
            {
                "gmail.googleapis.com",
                "www.googleapis.com",
                "docs.googleapis.com",
                "sheets.googleapis.com",
                "oauth2.googleapis.com",
            }
        ),
        identify=_identify,
        demo_label="Nile Labs Google Workspace (demo, simulated)",
        actions=[
            Action(
                "gmail_send", "Send an email with Gmail",
                "Send an email from the user's Gmail. A person approves it before it is sent.",
                MAIL_SCHEMA, HIGH, ("https://www.googleapis.com/auth/gmail.send",),
                _send_preview, _send, _demo("mail"), _mail_checks,
            ),
            Action(
                "gmail_draft", "Save a Gmail draft",
                "Save an email draft in the user's Gmail. Nothing is sent. Needs approval.",
                obj(MAIL_SCHEMA["properties"], ["subject", "body"]), MEDIUM, ("https://www.googleapis.com/auth/gmail.compose",),
                _draft_preview, _draft, _demo("drafts"), lambda a: _mail_checks(a, need_to=False),
            ),
            Action(
                "calendar_create_event", "Add a Google Calendar event",
                "Create an event in the user's primary Google Calendar. Guests get invites only when notify_attendees is true. Needs approval.",
                EVENT_SCHEMA, MEDIUM, ("https://www.googleapis.com/auth/calendar.events",),
                lambda a, c=None: event_preview("Google Calendar", a), _event, _demo("calendar"), event_checks,
            ),
            Action(
                "docs_create", "Create a Google Doc",
                "Create a Google Doc with a title and optional text. Needs approval.",
                obj({"title": text(200, 1), "body": text(50000)}, ["title"]), MEDIUM, ("https://www.googleapis.com/auth/documents",),
                lambda a, c=None: f"Create Google Doc “{short(a['title'], 90)}”" + (f" with {size_label(a['body'])} of text" if a.get("body") else ""),
                _doc, _demo("docs"), lambda a: single_line(a.get("title", ""), "title"),
            ),
            Action(
                "sheets_append", "Append rows to a Google Sheet",
                "Append rows of plain values to a Google Sheet. Values are stored as text, never as formulas. Needs approval.",
                SHEETS_SCHEMA, MEDIUM, ("https://www.googleapis.com/auth/spreadsheets",),
                _sheet_preview, _sheet, _demo("sheets"), _sheet_checks,
            ),
            Action(
                "drive_upload", "Upload a file to Google Drive",
                "Upload a text file (plain text, Markdown, CSV or HTML) to Google Drive. Needs approval.",
                UPLOAD_SCHEMA, MEDIUM, ("https://www.googleapis.com/auth/drive.file",),
                lambda a, c=None: f"Upload “{short(a['name'], 80)}” ({size_label(a['content'])}) to Google Drive",
                _upload, _demo("drive"), file_checks,
            ),
        ],
    )
)
