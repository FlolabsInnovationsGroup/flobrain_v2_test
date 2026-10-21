"""Jira Cloud (Atlassian OAuth 2.0 3LO): create an issue, comment, move an issue to a status."""

import re
import secrets
import urllib.parse

from integrations.write.registry import MEDIUM, Action, Provider, obj, register, short, single_line, text

API = "https://api.atlassian.com"
PROJECT_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,9}$")
ISSUE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,9}-\d{1,7}$")
CLOUD_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
SITE_RE = re.compile(r"^https://[a-z0-9][a-z0-9-]{0,62}\.atlassian\.net$")


def adf(value: str) -> dict:
    """Atlassian Document Format: one paragraph per line block, plain text only."""
    paragraphs = [p for p in (value or "").split("\n\n") if p.strip()] or [""]
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": p}] if p else []} for p in paragraphs],
    }


def _base(conn) -> str:
    cloud = str((conn.config or {}).get("cloud_id") or "")
    if not CLOUD_RE.match(cloud):
        raise ValueError("Jira site is not known. Connect Jira again.")
    return f"{API}/ex/jira/{cloud}/rest/api/3"


def _browse(conn, key: str, suffix: str = "") -> str:
    site = str((conn.config or {}).get("site_url") or "")
    return f"{site}/browse/{urllib.parse.quote(key)}{suffix}" if SITE_RE.match(site) else ""


def _issue_checks(args):
    if not PROJECT_RE.match(args["project_key"]):
        raise ValueError("project_key looks like APP or MOBILE")
    single_line(args["summary"], "summary")


def _issue_preview(args, conn=None):
    kind = args.get("issue_type") or "Task"
    return f"Create Jira {kind} in {args['project_key']}: “{short(args['summary'], 100)}”"


def _create(client, args, conn):
    fields = {
        "project": {"key": args["project_key"]},
        "summary": args["summary"],
        "issuetype": {"name": args.get("issue_type") or "Task"},
    }
    if args.get("description"):
        fields["description"] = adf(args["description"])
    if args.get("labels"):
        fields["labels"] = args["labels"]
    data = client.call("POST", f"{_base(conn)}/issue", json_body={"fields": fields})
    key = str(data.get("key") or "")
    return {"id": key, "url": _browse(conn, key) if key else "", "title": f"{key} {args['summary']}".strip()}


def _key_checks(args):
    if not ISSUE_RE.match(args["issue_key"]):
        raise ValueError("issue_key looks like APP-123")


def _comment(client, args, conn):
    key = args["issue_key"]
    data = client.call("POST", f"{_base(conn)}/issue/{urllib.parse.quote(key)}/comment", json_body={"body": adf(args["body"])})
    cid = str(data.get("id") or "")
    return {"id": cid, "url": _browse(conn, key, f"?focusedCommentId={urllib.parse.quote(cid)}" if cid else ""), "title": key}


def _transition(client, args, conn):
    key = args["issue_key"]
    path = f"{_base(conn)}/issue/{urllib.parse.quote(key)}/transitions"
    data = client.call("GET", path)
    wanted = args["to_status"].strip().lower()
    match = None
    for t in data.get("transitions") or [] if isinstance(data, dict) else []:
        if not isinstance(t, dict):
            continue
        names = {str(t.get("name") or "").lower(), str((t.get("to") or {}).get("name") or "").lower()}
        if wanted in names:
            match = t
            break
    if match is None:
        raise ValueError(f"{key} can't move to “{short(args['to_status'], 40)}” from where it is now")
    client.call("POST", path, json_body={"transition": {"id": str(match.get("id"))}})
    return {"id": key, "url": _browse(conn, key), "title": f"{key} → {args['to_status']}"}


def _identify(client, token):
    data = client.call("GET", f"{API}/oauth/token/accessible-resources")
    site = next((s for s in data if isinstance(s, dict)), None) if isinstance(data, list) else None
    if site is None or not CLOUD_RE.match(str(site.get("id") or "")):
        raise ValueError("No Jira site is available to this account")
    url = str(site.get("url") or "").rstrip("/")
    config = {"cloud_id": str(site["id"]), "site_url": url if SITE_RE.match(url) else ""}
    return str(site.get("name") or url or "Jira site")[:160], config


def _demo(kind):
    def make(args):
        if kind == "issue":
            key = f"{args['project_key']}-{secrets.randbelow(900) + 100}"
            return {"id": key, "url": f"https://jira.example.com/browse/{key}", "title": f"{key} {args['summary']}"}
        key = args["issue_key"]
        return {"id": key, "url": f"https://jira.example.com/browse/{key}", "title": key}

    return make


register(
    Provider(
        key="jira",
        name="Jira",
        description="Create issues, add comments and move issues between statuses.",
        authorize_url="https://auth.atlassian.com/authorize",
        token_url="https://auth.atlassian.com/oauth/token",
        base_scopes=("offline_access", "read:jira-work"),
        auth_params={"audience": "api.atlassian.com", "prompt": "consent"},
        hosts=frozenset({"api.atlassian.com", "auth.atlassian.com"}),
        identify=_identify,
        demo_label="nile-labs.atlassian.net (demo, simulated)",
        demo_config={"cloud_id": "00000000-0000-4000-8000-000000000000", "site_url": "", "default_project": "APP"},
        actions=[
            Action(
                "create_issue", "Create a Jira issue",
                "Create a Jira issue (Task, Bug or Story) in a project. Needs approval.",
                obj(
                    {
                        "project_key": text(10, 2),
                        "summary": text(255, 1),
                        "description": text(30000),
                        "issue_type": {"type": "string", "enum": ["Task", "Bug", "Story"]},
                        "labels": {"type": "array", "items": text(50, 1), "maxItems": 10},
                    },
                    ["project_key", "summary"],
                ),
                MEDIUM, ("write:jira-work",), _issue_preview, _create, _demo("issue"), _issue_checks,
            ),
            Action(
                "add_comment", "Comment on a Jira issue",
                "Add a comment to a Jira issue. Needs approval.",
                obj({"issue_key": text(20, 3), "body": text(30000, 1)}, ["issue_key", "body"]),
                MEDIUM, ("write:jira-work",),
                lambda a, c=None: f"Comment on Jira {a['issue_key']}: “{short(a['body'], 100)}”",
                _comment, _demo("comment"), _key_checks,
            ),
            Action(
                "transition_issue", "Move a Jira issue",
                "Move a Jira issue to another status, like In Progress or Done. Needs approval.",
                obj({"issue_key": text(20, 3), "to_status": text(60, 1)}, ["issue_key", "to_status"]),
                MEDIUM, ("write:jira-work",),
                lambda a, c=None: f"Move Jira {a['issue_key']} to “{short(a['to_status'], 40)}”",
                _transition, _demo("transition"), _key_checks,
            ),
        ],
    )
)
