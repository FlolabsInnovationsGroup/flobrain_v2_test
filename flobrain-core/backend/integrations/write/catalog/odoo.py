"""Odoo through its JSON-RPC API with a user's API key: create a CRM lead, a draft customer invoice
(never posted or sent), or a project task.

Odoo has no platform OAuth app, so an admin enters the instance URL, database, login and an API key.
The key is stored encrypted. The instance must be on ``*.odoo.com`` or listed in
``FLOBRAIN_ODOO_ALLOWED_HOSTS`` (comma separated), and must resolve to a public address.
"""

import re
import secrets
import urllib.parse
from decimal import Decimal

from integrations.write.registry import (
    EMAIL,
    HIGH,
    MEDIUM,
    Action,
    Provider,
    decimal,
    env,
    obj,
    register,
    short,
    single_line,
    text,
)
from integrations.write.transport import WriteError, raw_request

DB_RE = re.compile(r"^[A-Za-z0-9_.-]{1,63}$")
KEY_RE = re.compile(r"^[\x21-\x7e]{8,256}$")


def extra_hosts() -> set[str]:
    return {h.strip().lower() for h in env("FLOBRAIN_ODOO_ALLOWED_HOSTS").split(",") if h.strip()}


def host_permitted(host: str) -> bool:
    host = (host or "").lower()
    return host.endswith(".odoo.com") or host in extra_hosts()


def _host_rule(host, connection) -> bool:
    configured = urllib.parse.urlparse(str(((connection.config if connection is not None else None) or {}).get("url") or "")).hostname
    return bool(configured) and host == configured.lower() and host_permitted(host)


def normalize_url(value: str) -> str | None:
    """``https://host`` for an allowed Odoo instance, else None."""
    try:
        parsed = urllib.parse.urlparse((value or "").strip())
        port = parsed.port
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or port not in (None, 443):
        return None
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return None
    return f"https://{host}" if host_permitted(host) else None


def _rpc(conn, service, method, args):
    provider = PROVIDER
    url = f"{conn.config['url']}/jsonrpc"
    body = {"jsonrpc": "2.0", "method": "call", "params": {"service": service, "method": method, "args": args}, "id": secrets.randbelow(10**6)}
    import json

    status, parsed = raw_request(provider, "POST", url, body=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, connection=conn)
    if status != 200 or not isinstance(parsed, dict):
        raise WriteError("provider_error", f"Odoo answered {status}")
    if parsed.get("error"):
        err = parsed["error"] if isinstance(parsed["error"], dict) else {}
        data = err.get("data") if isinstance(err.get("data"), dict) else {}
        message = " ".join(str(data.get("message") or err.get("message") or "error").split())[:120]
        if "AccessDenied" in str(data.get("name") or "") or "Access Denied" in message:
            raise WriteError("expired", "Odoo refused the API key. Connect Odoo again.")
        raise WriteError("provider_error", f"Odoo: {message}")
    return parsed.get("result")


def authenticate(conn, login: str, api_key: str) -> int:
    uid = _rpc(conn, "common", "authenticate", [conn.config["database"], login, api_key, {}])
    if not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0:
        raise WriteError("invalid_credential", "Odoo did not accept that login and API key")
    return uid


def _execute(conn, model, method, args, kwargs=None):
    from integrations.crypto import CredentialCryptoError

    try:
        key = conn.access_token()
    except CredentialCryptoError as exc:
        raise WriteError("expired", "Connect Odoo again") from exc
    uid = (conn.config or {}).get("uid")
    if not isinstance(uid, int):
        raise WriteError("expired", "Connect Odoo again")
    return _rpc(conn, "object", "execute_kw", [conn.config["database"], uid, key, model, method, args, kwargs or {}])


def _link(conn, model, record_id) -> str:
    if not isinstance(record_id, int):
        return ""
    return f"{conn.config['url']}/web#id={record_id}&model={model}&view_type=form"


def _lead_checks(args):
    single_line(args["name"], "name")
    decimal(args.get("expected_revenue"), "expected_revenue")


def _lead_preview(args, conn=None):
    who = args.get("contact_name") or args.get("company") or ""
    mail = f" ({args['email']})" if args.get("email") else ""
    return f"Create Odoo lead “{short(args['name'], 80)}”" + (f" for {short(who, 60)}{mail}" if who or mail else "")


def _lead(client, args, conn):
    values = {"name": args["name"], "type": "lead"}
    for src, dst in (("contact_name", "contact_name"), ("email", "email_from"), ("company", "partner_name"), ("description", "description")):
        if args.get(src):
            values[dst] = args[src]
    if args.get("expected_revenue"):
        values["expected_revenue"] = float(Decimal(args["expected_revenue"]))
    rid = _execute(conn, "crm.lead", "create", [values])
    return {"id": str(rid), "url": _link(conn, "crm.lead", rid), "title": args["name"]}


LINE = obj({"description": text(200, 1), "quantity": {"type": "integer", "minimum": 1, "maximum": 100000}, "unit_price": text(16, 1)}, ["description", "unit_price"])


def invoice_total(lines) -> Decimal:
    return sum((Decimal(line["unit_price"]) * int(line.get("quantity") or 1) for line in lines), Decimal("0"))


def _invoice_checks(args):
    single_line(args["customer"], "customer")
    if not args["lines"]:
        raise ValueError("add at least one invoice line")
    for line in args["lines"]:
        decimal(line["unit_price"], "unit_price")
        single_line(line["description"], "description")


def _invoice_preview(args, conn=None):
    n = len(args["lines"])
    return (
        f"Create a draft Odoo invoice for {short(args['customer'], 60)}: {n} line{'s' if n != 1 else ''}, "
        f"total {invoice_total(args['lines']):,.2f} (draft only, not posted or sent)"
    )


def _invoice(client, args, conn):
    ids = _execute(conn, "res.partner", "search", [[["name", "=ilike", args["customer"]]]], {"limit": 1})
    if not isinstance(ids, list) or not ids or not isinstance(ids[0], int):
        raise WriteError("not_found", f"No Odoo customer named “{short(args['customer'], 60)}”")
    values = {
        "move_type": "out_invoice",
        "partner_id": ids[0],
        "invoice_line_ids": [
            [0, 0, {"name": line["description"], "quantity": int(line.get("quantity") or 1), "price_unit": float(Decimal(line["unit_price"]))}]
            for line in args["lines"]
        ],
    }
    if args.get("due_date"):
        values["invoice_date_due"] = args["due_date"]
    if args.get("reference"):
        values["ref"] = args["reference"]
    rid = _execute(conn, "account.move", "create", [values])  # created in draft state; never posted here
    return {"id": str(rid), "url": _link(conn, "account.move", rid), "title": f"Draft invoice for {args['customer']}"}


def _task(client, args, conn):
    values = {"name": args["name"], "project_id": args["project_id"]}
    if args.get("description"):
        values["description"] = args["description"]
    if args.get("deadline"):
        values["date_deadline"] = args["deadline"]
    rid = _execute(conn, "project.task", "create", [values])
    return {"id": str(rid), "url": _link(conn, "project.task", rid), "title": args["name"]}


def _demo(model):
    def make(args):
        n = secrets.randbelow(9000) + 1000
        title = args.get("name") or (f"Draft invoice for {args['customer']}" if args.get("customer") else "Odoo record")
        return {"id": str(n), "url": f"https://odoo.example.com/web#id={n}&model={model}&view_type=form", "title": title}

    return make


PROVIDER = register(
    Provider(
        key="odoo",
        name="Odoo",
        description="Create CRM leads, draft customer invoices and project tasks in your Odoo.",
        auth="api_key",
        host_rule=_host_rule,
        demo_label="nile-labs.odoo.com (demo, simulated)",
        demo_config={"url": "https://odoo.example.com", "database": "nile-labs", "login": "ops@demo.flobrain.example"},
        actions=[
            Action(
                "create_lead", "Create an Odoo lead",
                "Create a lead in Odoo CRM. expected_revenue is a plain number. Needs approval.",
                obj(
                    {"name": text(200, 1), "contact_name": text(120), "email": EMAIL, "company": text(120), "expected_revenue": text(16), "description": text(8000)},
                    ["name"],
                ),
                MEDIUM, (), _lead_preview, _lead, _demo("crm.lead"), _lead_checks,
            ),
            Action(
                "create_invoice_draft", "Draft an Odoo invoice",
                "Create a draft customer invoice in Odoo for an existing customer. It is not posted or sent. Needs approval.",
                obj(
                    {
                        "customer": text(200, 1),
                        "lines": {"type": "array", "items": LINE, "maxItems": 50},
                        "due_date": {"type": "string", "format": "date"},
                        "reference": text(60),
                    },
                    ["customer", "lines"],
                ),
                HIGH, (), _invoice_preview, _invoice, _demo("account.move"), _invoice_checks,
            ),
            Action(
                "create_task", "Create an Odoo task",
                "Create a task in an Odoo project (project_id is the Odoo project number). Needs approval.",
                obj(
                    {"name": text(200, 1), "project_id": {"type": "integer", "minimum": 1, "maximum": 10**9}, "description": text(8000), "deadline": {"type": "string", "format": "date"}},
                    ["name", "project_id"],
                ),
                MEDIUM, (),
                lambda a, c=None: f"Create Odoo task “{short(a['name'], 80)}” in project {a['project_id']}",
                _task, _demo("project.task"), lambda a: single_line(a["name"], "name"),
            ),
        ],
    )
)
