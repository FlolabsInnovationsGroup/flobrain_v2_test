"""Demo model answers for write-back connectors (``DEMO_AI`` only).

When a buddy that offers connector tools is asked to write somewhere ("create a Jira issue for the
Android login bug", "send the NDA to counsel by Gmail", "add Mona to HubSpot"), the demo model
returns a tool call for the right action, so the approval card appears. Nothing runs until a person
approves it, and the demo connections are simulated: no network is used.

Only buddy turns that offer at least one connector tool are handled; everything else passes on.
"""

import json
import re
from datetime import datetime, timedelta, timezone

from brain.llm.demo_ai import _question, _result

BUDDY_MARK = "You are a FloBrain buddy"
PROVIDERS = ("google_workspace", "microsoft_365", "jira", "hubspot", "odoo", "zoho")
LABEL = "(Prepared by FloBrain's demo model. The connection is simulated.)"
I = re.IGNORECASE
EMAIL_RE = re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63})+")
ISSUE_RE = re.compile(r"\b([A-Z][A-Z0-9_]{1,9}-\d{1,7})\b")
AMOUNT_RE = re.compile(r"(\d[\d,]*(?:\.\d{1,2})?)\s*(k)?\b", I)
CAIRO = timezone(timedelta(hours=2))


def _names(tools):
    return {t.get("function", {}).get("name", "") for t in tools or []}


def _fn(provider, action):
    return f"{provider}__{action}"


def _clean(value, limit=120):
    value = re.sub(r"\s+", " ", value or "").strip(" .,:;!?\"'“”")
    return (value[:1].upper() + value[1:])[:limit] if value else ""


def _after(pattern, text, flags=I):
    match = re.search(pattern, text, flags)
    return _clean(match.group(1)) if match else ""


def _amount(text):
    for match in AMOUNT_RE.finditer(text):
        raw = match.group(1).replace(",", "")
        if ISSUE_RE.search(text[max(0, match.start() - 12) : match.end()]):
            continue
        value = float(raw) * (1000 if match.group(2) else 1)
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return ""


def _recipient(text):
    found = EMAIL_RE.findall(text)
    if found:
        return found[:5]
    match = re.search(r"\bto\s+(?:our\s+|the\s+|my\s+)?([A-Za-z][\w.-]{1,40})", text, I)
    word = match.group(1).lower() if match else "team"
    if word in ("gmail", "outlook", "email", "mail", "me"):
        word = "team"
    return [f"{word}@example.com"]


def _mail(q, names):
    if not re.search(r"\b(gmail|outlook|e-?mail|mail)\b", q, I) or not re.search(r"\b(send|email|mail|draft|write)\b", q, I):
        return None
    draft = bool(re.search(r"\bdraft\b", q, I))
    if re.search(r"\boutlook\b", q, I) and _fn("microsoft_365", "outlook_send") in names and not draft:
        fn = _fn("microsoft_365", "outlook_send")
    else:
        fn = _fn("google_workspace", "gmail_draft" if draft else "gmail_send")
    if fn not in names:
        return None
    subject = _after(r"\b(?:send|draft|email|mail|write)\s+(?:an?\s+|the\s+|our\s+)?(?:email\s+(?:about\s+)?)?(.+?)\s+to\b", q)
    if subject.lower() in ("", "email", "an email", "mail"):
        subject = _after(r"\babout\s+(?:the\s+)?(.+?)(?:\s+(?:by|via|with|in|on)\s+(?:gmail|outlook|e-?mail).*)?$", q) or "Quick follow-up"
    body = f"Hello,\n\nSharing the {subject} for your review. Let me know if anything needs to change.\n\nBest regards\n\n{LABEL}"
    return fn, {"to": _recipient(q), "subject": subject, "body": body}


def _jira(q, names):
    if not re.search(r"\bjira\b", q, I) and not ISSUE_RE.search(q):
        return None
    key = ISSUE_RE.search(q)
    move = re.search(r"\b(?:move|transition|mark)\b.*?\bto\s+(.+)$", q, I)
    if key and move and _fn("jira", "transition_issue") in names:
        return _fn("jira", "transition_issue"), {"issue_key": key.group(1), "to_status": _clean(move.group(1), 60) or "Done"}
    if key and re.search(r"\bcomment\b", q, I) and _fn("jira", "add_comment") in names:
        body = _after(r":\s*(.+)$", q, I) or _after(rf"{key.group(1)}\s+(?:saying|that)?\s*(.+)$", q, I) or "Following up on this."
        return _fn("jira", "add_comment"), {"issue_key": key.group(1), "body": body}
    if _fn("jira", "create_issue") not in names or not re.search(r"\b(issue|bug|ticket|story|task)\b", q, I):
        return None
    summary = _after(r"\b(?:issue|bug|ticket|story|task)\b\s*(?:for|about|on|:)?\s*(?:the\s+)?(.+?)(?:\s+in\s+(?:project\s+)?[A-Z]{2,10})?$", q) or "Follow up"
    summary = re.sub(r"\s+(?:in|on)\s+jira$", "", summary, flags=I)
    kind = "Bug" if re.search(r"\bbug\b", q, I) else "Story" if re.search(r"\bstory\b", q, I) else "Task"
    project = re.search(r"\bin\s+(?:project\s+)?([A-Z][A-Z0-9_]{1,9})\b", q)
    args = {"project_key": project.group(1) if project and project.group(1) != "JIRA" else "APP", "summary": summary, "issue_type": kind}
    args["description"] = f"Reported from a FloBrain buddy chat.\n\n{LABEL}"
    return _fn("jira", "create_issue"), args


def _person(q):
    match = re.search(r"\b(?i:add|create|new contact|contact|lead for|for)\s+([A-Z][a-z]+)(?:\s+(?!To\b|In\b|As\b|From\b)([A-Z][a-z]+))?", q)
    if not match:
        return "", ""
    return match.group(1), match.group(2) or ""


def _hubspot(q, names):
    if not re.search(r"\bhub\s?spot\b", q, I):
        return None
    if re.search(r"\bdeal\b", q, I) and _fn("hubspot", "create_deal") in names:
        name = _after(r"\bdeal\s+(?:for|with|called|named)\s+(.+?)(?:\s+(?:worth|for|of)\s+[\d$].*)?(?:\s+(?:in|on)\s+hub\s?spot.*)?$", q) or "New deal"
        args = {"dealname": name}
        if _amount(q):
            args["amount"] = _amount(q)
        return _fn("hubspot", "create_deal"), args
    if re.search(r"\bnote\b", q, I) and _fn("hubspot", "log_note") in names:
        args = {"body": _after(r":\s*(.+)$", q) or f"Call notes. {LABEL}"}
        emails = EMAIL_RE.findall(q)
        if emails:
            args["contact_email"] = emails[0]
        return _fn("hubspot", "log_note"), args
    if _fn("hubspot", "create_contact") not in names:
        return None
    first, last = _person(q)
    emails = EMAIL_RE.findall(q)
    email = emails[0] if emails else f"{(first or 'new.contact').lower()}{('.' + last.lower()) if last else ''}@example.com"
    args = {"email": email}
    if first:
        args["firstname"] = first
    if last:
        args["lastname"] = last
    company = _after(r"\bfrom\s+([A-Z][\w&.\- ]{1,60}?)(?:\s+(?:to|in|on)\b|$)", q, 0)
    if company:
        args["company"] = company
    return _fn("hubspot", "create_contact"), args


def _customer(q, default):
    return _after(r"\bfor\s+([A-Z][\w&.\- ]{1,60}?)(?:\s+(?:in|on|of|worth|with)\b|$)", q, 0) or default


def _odoo(q, names):
    if not re.search(r"\bodoo\b", q, I):
        return None
    q = re.sub(r"\s*\b(?:in|on|to)\s+odoo\b", "", q, flags=I)
    if re.search(r"\binvoice\b", q, I) and _fn("odoo", "create_invoice_draft") in names:
        price = _amount(q) or "1500"
        return _fn("odoo", "create_invoice_draft"), {
            "customer": _customer(q, "Delta Trading"),
            "lines": [{"description": "Consulting services", "quantity": 1, "unit_price": price}],
        }
    if re.search(r"\btask\b", q, I) and _fn("odoo", "create_task") in names:
        name = _after(r"\btask\b\s*(?:to|for|:)?\s*(.+?)(?:\s+(?:in|on)\s+odoo.*)?$", q) or "Follow up"
        return _fn("odoo", "create_task"), {"name": name, "project_id": 1}
    if _fn("odoo", "create_lead") in names:
        name = _after(r"\blead\b\s*(?:for|from|:)?\s*(.+?)(?:\s+(?:in|on)\s+odoo.*)?$", q) or "New lead"
        return _fn("odoo", "create_lead"), {"name": name}
    return None


def _zoho(q, names):
    if not re.search(r"\bzoho\b", q, I):
        return None
    if re.search(r"\binvoice\b", q, I) and _fn("zoho", "books_create_invoice") in names:
        return _fn("zoho", "books_create_invoice"), {
            "customer_id": "460000000012345",
            "customer_name": _customer(q, "Delta Trading"),
            "line_items": [{"name": "Consulting services", "rate": _amount(q) or "1500", "quantity": 1}],
        }
    if re.search(r"\bdeal\b", q, I) and _fn("zoho", "crm_create_deal") in names:
        name = _after(r"\bdeal\s+(?:for|with|called|named)\s+(.+?)(?:\s+(?:worth|in|on)\b.*)?$", q) or "New deal"
        args = {"deal_name": name}
        if _amount(q):
            args["amount"] = _amount(q)
        return _fn("zoho", "crm_create_deal"), args
    if _fn("zoho", "crm_create_lead") in names:
        first, last = _person(q)
        company = _after(r"\b(?:from|at)\s+([A-Z][\w&.\- ]{1,60}?)(?:\s+(?:in|on|to)\b|$)", q, 0) or "Unknown company"
        args = {"last_name": last or first or "Lead", "company": company}
        if first and last:
            args["first_name"] = first
        return _fn("zoho", "crm_create_lead"), args
    return None


def _calendar(q, names):
    if not re.search(r"\b(calendar|meeting|event|invite)\b", q, I) or not re.search(r"\b(add|create|schedule|book|put|invite)\b", q, I):
        return None
    if re.search(r"\boutlook\b", q, I) and _fn("microsoft_365", "calendar_create_event") in names:
        fn = _fn("microsoft_365", "calendar_create_event")
    elif _fn("google_workspace", "calendar_create_event") in names:
        fn = _fn("google_workspace", "calendar_create_event")
    else:
        return None
    start = (datetime.now(CAIRO) + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    title = _after(r"\b(?:meeting|event|call)\s+(?:with|about|for)\s+(.+?)(?:\s+(?:on|at|tomorrow|to|in)\b.*)?$", q) or "Team sync"
    args = {"title": title, "starts_at": start.isoformat(), "ends_at": (start + timedelta(minutes=30)).isoformat()}
    guests = EMAIL_RE.findall(q)
    if guests:
        args["attendees"] = guests[:10]
    return fn, args


def _teams(q, names):
    fn = _fn("microsoft_365", "teams_post_message")
    if fn not in names or not re.search(r"\bteams\b", q, I) or not re.search(r"\b(post|message|tell|share|say)\b", q, I):
        return None
    body = _after(r"(?::|\bsaying|\bthat)\s+(.+)$", q) or "Quick update from FloBrain."
    return fn, {"team_id": "11111111-2222-4333-8444-555555555555", "channel_id": "19:general@thread.tacv2", "channel_name": "General", "body": body}


def _files(q, names):
    if re.search(r"\bgoogle\s+docs?\b", q, I) and _fn("google_workspace", "docs_create") in names:
        title = _after(r"\bdoc(?:ument)?\b\s*(?:for|about|called|named|:)?\s*(?:the\s+)?(.+)$", q) or "Meeting notes"
        return _fn("google_workspace", "docs_create"), {"title": title, "body": f"{title}\n\n{LABEL}"}
    if re.search(r"\b(sheet|spreadsheet)\b", q, I) and _fn("google_workspace", "sheets_append") in names:
        row = _after(r":\s*(.+)$", q) or "New row"
        return _fn("google_workspace", "sheets_append"), {
            "spreadsheet_id": "1DemoSheetNileLabsPipeline0000",
            "spreadsheet_name": "Pipeline tracker",
            "sheet": "Sheet1",
            "rows": [[part.strip() for part in row.split(",")][:10]],
        }
    if re.search(r"\bone\s?drive\b", q, I) and _fn("microsoft_365", "onedrive_upload") in names:
        return _fn("microsoft_365", "onedrive_upload"), {"name": "notes.md", "content": f"# Notes\n\n{LABEL}\n"}
    if re.search(r"\b(google\s+)?drive\b", q, I) and re.search(r"\b(upload|save|put)\b", q, I) and _fn("google_workspace", "drive_upload") in names:
        return _fn("google_workspace", "drive_upload"), {"name": "notes.md", "content": f"# Notes\n\n{LABEL}\n", "mime_type": "text/markdown"}
    return None


MATCHERS = (_jira, _hubspot, _odoo, _zoho, _teams, _mail, _calendar, _files)


def handle(system, user, messages, tools):
    if not tools or BUDDY_MARK not in (system or ""):
        return None
    names = _names(tools)
    if not any(n.split("__", 1)[0] in PROVIDERS for n in names):
        return None
    question = (_question(messages) or user or "").strip()
    for matcher in MATCHERS:
        hit = matcher(question, names)
        if hit is not None:
            fn, args = hit
            text = f"I prepared this for your approval. Nothing is sent or changed until you approve it. {LABEL}"
            return _result(text, [{"name": fn, "arguments": json.dumps(args)}])
    return None
