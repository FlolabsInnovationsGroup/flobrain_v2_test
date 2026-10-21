"""Microsoft 365 through Microsoft Graph: Outlook send, Calendar event, Teams channel message,
OneDrive upload."""

import re
import secrets
import urllib.parse

from django.utils.dateparse import parse_datetime

from integrations.write.catalog.google import EVENT_SCHEMA, event_checks, event_preview, file_checks, size_label
from integrations.write.registry import (
    EMAILS,
    HIGH,
    MEDIUM,
    Action,
    Provider,
    env,
    obj,
    recipients,
    register,
    short,
    single_line,
    text,
)

GRAPH = "https://graph.microsoft.com/v1.0"
TENANT_RE = re.compile(r"^[A-Za-z0-9.-]{1,64}$")
CHANNEL_RE = re.compile(r"^19:[A-Za-z0-9_.@-]{1,120}$")
UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
FOLDER_RE = re.compile(r"^[A-Za-z0-9 _.-]{1,80}$")


def _tenant() -> str:
    value = env("FLOBRAIN_OAUTH_MICROSOFT_365_TENANT") or "common"
    return value if TENANT_RE.match(value) else "common"


def _mail_checks(args):
    if not args.get("to"):
        raise ValueError("add at least one recipient")
    single_line(args.get("subject", ""), "subject")


def _send_preview(args, conn=None):
    cc = f" (cc {recipients(args['cc'])})" if args.get("cc") else ""
    return f"Send email from Outlook to {recipients(args['to'])}{cc}: Subject “{short(args['subject'], 90)}”"


def _send(client, args, conn):
    message = {
        "subject": args["subject"],
        "body": {"contentType": "Text", "content": args["body"]},
        "toRecipients": [{"emailAddress": {"address": e}} for e in args["to"]],
        "ccRecipients": [{"emailAddress": {"address": e}} for e in args.get("cc") or []],
    }
    client.call("POST", f"{GRAPH}/me/sendMail", json_body={"message": message, "saveToSentItems": True})
    return {"id": "", "url": "https://outlook.office.com/mail/sentitems", "title": args["subject"]}


OUTLOOK_EVENT_SCHEMA = obj({k: v for k, v in EVENT_SCHEMA["properties"].items() if k != "notify_attendees"}, EVENT_SCHEMA["required"])


def _utc(value: str) -> str:
    from datetime import timezone

    return parse_datetime(value).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _event(client, args, conn):
    body = {
        "subject": args["title"],
        "body": {"contentType": "Text", "content": args.get("description", "")},
        "start": {"dateTime": _utc(args["starts_at"]), "timeZone": "UTC"},
        "end": {"dateTime": _utc(args["ends_at"]), "timeZone": "UTC"},
        "location": {"displayName": args.get("location", "")},
        "attendees": [{"emailAddress": {"address": e}, "type": "required"} for e in args.get("attendees") or []],
    }
    data = client.call("POST", f"{GRAPH}/me/events", json_body=body)
    return {"id": str(data.get("id") or ""), "url": _https(data.get("webLink")), "title": args["title"]}


TEAMS_SCHEMA = obj(
    {"team_id": text(36, 36), "channel_id": text(130, 4), "channel_name": text(120), "body": text(20000, 1)},
    ["team_id", "channel_id", "body"],
)


def _teams_checks(args):
    if not UUID_RE.match(args["team_id"]):
        raise ValueError("team_id is not a Teams team id")
    if not CHANNEL_RE.match(args["channel_id"]):
        raise ValueError("channel_id is not a Teams channel id (it starts with 19:)")


def _teams_preview(args, conn=None):
    where = f"#{args['channel_name']}" if args.get("channel_name") else "a Teams channel"
    return f"Post in {short(where, 60)} on Microsoft Teams: “{short(args['body'], 100)}”"


def _teams(client, args, conn):
    team = urllib.parse.quote(args["team_id"], safe="")
    channel = urllib.parse.quote(args["channel_id"], safe="")
    data = client.call(
        "POST", f"{GRAPH}/teams/{team}/channels/{channel}/messages", json_body={"body": {"contentType": "text", "content": args["body"]}}
    )
    return {"id": str(data.get("id") or ""), "url": _https(data.get("webUrl")), "title": args.get("channel_name") or "Teams message"}


ONEDRIVE_SCHEMA = obj({"name": text(200, 1), "content": text(200000, 1), "folder": text(80)}, ["name", "content"])


def _onedrive_checks(args):
    file_checks(args)
    if args.get("folder") and not FOLDER_RE.match(args["folder"]):
        raise ValueError("folder may use letters, numbers, spaces, dots, dashes and underscores")


def _onedrive(client, args, conn):
    path = urllib.parse.quote(f"{args.get('folder') or 'FloBrain'}/{args['name']}")
    url = f"{GRAPH}/me/drive/root:/{path}:/content?@microsoft.graph.conflictBehavior=rename"
    data = client.call("PUT", url, body=args["content"].encode("utf-8"), content_type="text/plain; charset=utf-8")
    return {"id": str(data.get("id") or ""), "url": _https(data.get("webUrl")), "title": args["name"]}


def _https(value) -> str:
    return value if isinstance(value, str) and value.startswith("https://") else ""


def _identify(client, token):
    data = client.call("GET", f"{GRAPH}/me")
    label = str(data.get("mail") or data.get("userPrincipalName") or "") if isinstance(data, dict) else ""
    return (label or "Microsoft 365 account"), {}


def _demo(kind):
    def make(args):
        n = secrets.token_hex(4)
        title = args.get("subject") or args.get("title") or args.get("name") or args.get("channel_name") or "Teams message"
        return {"id": f"demo-{n}", "url": f"https://m365.example.com/{kind}/{n}", "title": title}

    return make


register(
    Provider(
        key="microsoft_365",
        name="Microsoft 365",
        description="Send Outlook email, add Calendar events, post in Teams channels, upload to OneDrive.",
        per_user=True,
        authorize_url=lambda: f"https://login.microsoftonline.com/{_tenant()}/oauth2/v2.0/authorize",
        token_url=lambda: f"https://login.microsoftonline.com/{_tenant()}/oauth2/v2.0/token",
        base_scopes=("offline_access", "User.Read"),
        auth_params={"response_mode": "query", "prompt": "select_account"},
        hosts=frozenset({"graph.microsoft.com", "login.microsoftonline.com"}),
        identify=_identify,
        demo_label="Nile Labs Microsoft 365 (demo, simulated)",
        actions=[
            Action(
                "outlook_send", "Send an email with Outlook",
                "Send an email from the user's Outlook mailbox. A person approves it before it is sent.",
                obj({"to": EMAILS, "cc": EMAILS, "subject": text(200, 1), "body": text(20000, 1)}, ["to", "subject", "body"]),
                HIGH, ("Mail.Send",), _send_preview, _send, _demo("mail"), _mail_checks,
            ),
            Action(
                "calendar_create_event", "Add an Outlook Calendar event",
                "Create an event in the user's Outlook calendar. Guests listed get invites. Needs approval.",
                OUTLOOK_EVENT_SCHEMA, MEDIUM, ("Calendars.ReadWrite",),
                lambda a, c=None: event_preview("Outlook", a), _event, _demo("calendar"), event_checks,
            ),
            Action(
                "teams_post_message", "Post in a Teams channel",
                "Post a message in a Microsoft Teams channel as the user. Needs approval.",
                TEAMS_SCHEMA, HIGH, ("ChannelMessage.Send",), _teams_preview, _teams, _demo("teams"), _teams_checks,
            ),
            Action(
                "onedrive_upload", "Upload a file to OneDrive",
                "Upload a text file to the user's OneDrive (folder FloBrain by default). Needs approval.",
                ONEDRIVE_SCHEMA, MEDIUM, ("Files.ReadWrite",),
                lambda a, c=None: f"Upload “{short(a['name'], 80)}” ({size_label(a['content'])}) to OneDrive/{a.get('folder') or 'FloBrain'}",
                _onedrive, _demo("onedrive"), _onedrive_checks,
            ),
        ],
    )
)
