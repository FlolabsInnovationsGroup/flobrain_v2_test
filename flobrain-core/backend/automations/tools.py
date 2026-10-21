"""Approval-gated tools that automation runs propose (registered in ``AutomationsConfig.ready``).

- ``automations.send_email``: sends one email through the platform mail backend. FloBrain has no
  other sending tool (``email.draft`` only saves a draft), so this one is registered here.
- ``automations.call_webhook``: POST/PUT JSON to an https host on the org's allowed list, through
  the SSRF-safe ``platform_api.net`` client (public addresses only, pinned, no redirects).
- ``automations.continue``: the ``wait_for_approval`` step. Approving it runs nothing by itself;
  the run resumes from ``automations.signals``.

Nothing is sent in demo mode: the result says ``simulated``.
"""

import json
import urllib.parse

from django.conf import settings

PERM = "automations.use"
UUID = {"type": "string", "format": "uuid"}

SEND_EMAIL = "automations.send_email"
CALL_WEBHOOK = "automations.call_webhook"
CONTINUE = "automations.continue"

SPECS = {
    SEND_EMAIL: {
        "perm_key": PERM,
        "flag": "automations",
        "risk": "external",
        "label": "Send an email from a workflow",
        "description": "Send one email for an automation run. It is sent only after you approve it.",
        "schema": {
            "type": "object",
            "properties": {
                "workflow": UUID,
                "run": UUID,
                "to": {"type": "array", "items": {"type": "string", "format": "email", "maxLength": 254}, "maxItems": 20},
                "subject": {"type": "string", "minLength": 1, "maxLength": 200},
                "body": {"type": "string", "minLength": 1, "maxLength": 20000},
            },
            "required": ["workflow", "run", "to", "subject", "body"],
            "additionalProperties": False,
        },
    },
    CALL_WEBHOOK: {
        "perm_key": PERM,
        "flag": "automations",
        "risk": "external",
        "label": "Call a webhook from a workflow",
        "description": "Send data to an outside address for an automation run. It is sent only after you approve it.",
        "schema": {
            "type": "object",
            "properties": {
                "workflow": UUID,
                "run": UUID,
                "url": {"type": "string", "minLength": 9, "maxLength": 500},
                "method": {"type": "string", "enum": ["POST", "PUT"]},
                "body": {"type": "string", "maxLength": 20000},
            },
            "required": ["workflow", "run", "url"],
            "additionalProperties": False,
        },
    },
    CONTINUE: {
        "perm_key": PERM,
        "flag": "automations",
        "risk": "write",
        "label": "Let a workflow continue",
        "description": "A workflow is paused until you approve. Approving lets the next steps run.",
        "schema": {
            "type": "object",
            "properties": {
                "workflow": UUID,
                "run": UUID,
                "message": {"type": "string", "maxLength": 300},
            },
            "required": ["workflow", "run"],
            "additionalProperties": False,
        },
    },
}


def _denied(code, details=""):
    from actions.service import ActionDenied

    return ActionDenied(code, details)


def _enabled(org, user):
    from organizations.flags import effective_flag
    from organizations.models import OrgMembership

    membership = OrgMembership.objects.filter(org=org, user=user).first()
    if not effective_flag(org, membership, "automations", default=False):
        raise _denied("not_available", "automations are switched off")


def _run(org, user, args):
    from automations.models import WorkflowRun

    run = WorkflowRun.objects.filter(pk=args.get("run"), org=org, workflow_id=args.get("workflow")).select_related("workflow").first()
    if run is None or run.workflow.run_as_id != user.id:
        raise _denied("not_found", "workflow run not found")
    return run


def host_allowed(org, url) -> tuple[bool, bool]:
    """(allowed, trusted) for an https URL's host under the org's automation settings."""
    from automations.models import AutomationSettings

    parsed = urllib.parse.urlparse(url or "")
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        return False, False
    row = AutomationSettings.objects.filter(org=org).first()
    allowed = set((row.webhook_hosts if row else []) or [])
    trusted = set((row.trusted_hosts if row else []) or [])
    return host in allowed, host in allowed and host in trusted


def demo_mode() -> bool:
    return bool(getattr(settings, "DEMO_MODE", False))


# --- send_email -------------------------------------------------------------------


def _check_email(user, org, args):
    _enabled(org, user)
    _run(org, user, args)
    if not args.get("to"):
        raise _denied("invalid", "no recipients")
    return f"Email “{args['subject'][:60]}” to {len(args['to'])} recipient(s)"


def _send_email(user, org, args):
    _check_email(user, org, args)
    if demo_mode():
        return {"sent": False, "simulated": True, "recipients": len(args["to"])}
    from django.core.mail import send_mail

    send_mail(args["subject"], args["body"], None, list(args["to"]), fail_silently=False)
    return {"sent": True, "recipients": len(args["to"])}


# --- call_webhook -----------------------------------------------------------------


def _check_webhook(user, org, args):
    _enabled(org, user)
    _run(org, user, args)
    allowed, _ = host_allowed(org, args["url"])
    if not allowed:
        raise _denied("permission", "that host is not on the allowed list")
    host = urllib.parse.urlparse(args["url"]).hostname
    return f"Send data to {host}"


def call(org, run_id, workflow_id, url, method, body) -> dict:
    """The outgoing request itself (also used for trusted hosts without an approval)."""
    if demo_mode():
        return {"status": 200, "simulated": True}
    from platform_api import net

    payload = json.dumps({"workflow": str(workflow_id), "run": str(run_id), "text": body or ""}).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "FloBrain-Automations/1"}
    try:
        status, _ = net.fetch(method or "POST", url, payload, headers, timeout=10, max_bytes=1024)
    except net.UnsafeURL as exc:
        raise _denied("invalid", f"unsafe address: {exc}") from exc
    except OSError as exc:
        raise _denied("invalid", "the address did not answer") from exc
    if not 200 <= status < 300:
        raise _denied("invalid", f"the address answered {status}")
    return {"status": status}


def _call_webhook(user, org, args):
    _check_webhook(user, org, args)
    return call(org, args["run"], args["workflow"], args["url"], args.get("method", "POST"), args.get("body", ""))


# --- continue ---------------------------------------------------------------------


def _check_continue(user, org, args):
    from automations.models import WorkflowRun

    _enabled(org, user)
    run = _run(org, user, args)
    if run.status != WorkflowRun.WAITING:
        raise _denied("invalid", "this run is not waiting")
    return f"Continue “{run.workflow.name[:60]}”"


def _continue(user, org, args):
    _check_continue(user, org, args)
    return {"approved": True}


def register():
    from actions.plugins import register_tool

    register_tool(SEND_EMAIL, SPECS[SEND_EMAIL], check=_check_email, execute=_send_email)
    register_tool(CALL_WEBHOOK, SPECS[CALL_WEBHOOK], check=_check_webhook, execute=_call_webhook)
    register_tool(CONTINUE, SPECS[CONTINUE], check=_check_continue, execute=_continue)
