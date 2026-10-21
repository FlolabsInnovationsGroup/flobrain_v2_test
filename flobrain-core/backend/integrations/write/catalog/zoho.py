"""Zoho: CRM lead and deal, Books draft invoice. The data center comes from
``FLOBRAIN_OAUTH_ZOHO_DC`` (com, eu, in, com.au, jp, sa, ca; default com)."""

import re
import secrets
import urllib.parse
from decimal import Decimal

from integrations.write.transport import WriteError
from integrations.write.registry import EMAIL, HIGH, MEDIUM, Action, Provider, decimal, env, obj, register, short, single_line, text

DCS = {"com": "zoho.com", "eu": "zoho.eu", "in": "zoho.in", "com.au": "zoho.com.au", "jp": "zoho.jp", "sa": "zoho.sa", "ca": "zohocloud.ca"}
API_DOMAINS = {"com": "zohoapis.com", "eu": "zohoapis.eu", "in": "zohoapis.in", "com.au": "zohoapis.com.au", "jp": "zohoapis.jp", "sa": "zohoapis.sa", "ca": "zohoapis.ca"}
ID_RE = re.compile(r"^\d{1,25}$")
HOSTS = frozenset({f"accounts.{d}" for d in DCS.values()} | {f"www.{d}" for d in API_DOMAINS.values()})


def dc() -> str:
    value = env("FLOBRAIN_OAUTH_ZOHO_DC") or "com"
    return value if value in DCS else "com"


def _api(conn) -> str:
    domain = str((conn.config or {}).get("api_domain") or "")
    host = urllib.parse.urlparse(domain).hostname or ""
    if not domain.startswith("https://") or host not in HOSTS:
        return f"https://www.{API_DOMAINS[(conn.config or {}).get('dc') or dc()]}"
    return f"https://{host}"


def _crm_link(conn, module, record_id) -> str:
    domain = DCS.get((conn.config or {}).get("dc") or dc(), "zoho.com")
    return f"https://crm.{domain}/crm/tab/{module}/{record_id}" if ID_RE.match(str(record_id or "")) else ""


def _crm_create(client, conn, module, record):
    data = client.call("POST", f"{_api(conn)}/crm/v6/{module}", json_body={"data": [record]})
    row = (data.get("data") or [{}])[0] if isinstance(data, dict) else {}
    if not isinstance(row, dict) or str(row.get("status") or "").lower() != "success":
        message = str((row or {}).get("message") or "Zoho did not create the record") if isinstance(row, dict) else "Zoho did not create the record"
        raise ValueError(short(message, 120))
    return str((row.get("details") or {}).get("id") or "")


def _lead_checks(args):
    for name in ("last_name", "first_name", "company"):
        single_line(args.get(name, ""), name)


def _lead_preview(args, conn=None):
    who = " ".join(p for p in (args.get("first_name"), args["last_name"]) if p)
    mail = f" <{args['email']}>" if args.get("email") else ""
    return f"Create Zoho CRM lead {who}{mail} at {short(args['company'], 60)}"


def _lead(client, args, conn):
    record = {"Last_Name": args["last_name"], "Company": args["company"]}
    for src, dst in (("first_name", "First_Name"), ("email", "Email"), ("phone", "Phone"), ("description", "Description")):
        if args.get(src):
            record[dst] = args[src]
    rid = _crm_create(client, conn, "Leads", record)
    return {"id": rid, "url": _crm_link(conn, "Leads", rid), "title": f"{args.get('first_name', '')} {args['last_name']}".strip()}


def _deal_checks(args):
    single_line(args["deal_name"], "deal_name")
    decimal(args.get("amount"), "amount")


def _deal(client, args, conn):
    record = {"Deal_Name": args["deal_name"], "Stage": args.get("stage") or "Qualification"}
    if args.get("amount"):
        record["Amount"] = float(Decimal(args["amount"]))
    if args.get("closing_date"):
        record["Closing_Date"] = args["closing_date"]
    rid = _crm_create(client, conn, "Deals", record)
    return {"id": rid, "url": _crm_link(conn, "Potentials", rid), "title": args["deal_name"]}


LINE = obj({"name": text(200, 1), "rate": text(16, 1), "quantity": {"type": "integer", "minimum": 1, "maximum": 100000}}, ["name", "rate"])


def _total(lines) -> Decimal:
    return sum((Decimal(line["rate"]) * int(line.get("quantity") or 1) for line in lines), Decimal("0"))


def _invoice_checks(args):
    if not ID_RE.match(args["customer_id"]):
        raise ValueError("customer_id is the Zoho Books customer number")
    if not args["line_items"]:
        raise ValueError("add at least one line")
    for line in args["line_items"]:
        decimal(line["rate"], "rate")
        single_line(line["name"], "name")


def _invoice_preview(args, conn=None):
    who = args.get("customer_name") or f"customer {args['customer_id']}"
    n = len(args["line_items"])
    return f"Create a draft Zoho Books invoice for {short(who, 60)}: {n} line{'s' if n != 1 else ''}, total {_total(args['line_items']):,.2f} (draft only, not sent)"


def _invoice(client, args, conn):
    org = str((conn.config or {}).get("books_org_id") or "")
    if not ID_RE.match(org):
        raise ValueError("No Zoho Books organization is linked. Connect Zoho again.")
    body = {
        "customer_id": args["customer_id"],
        "line_items": [{"name": line["name"], "rate": float(Decimal(line["rate"])), "quantity": int(line.get("quantity") or 1)} for line in args["line_items"]],
    }
    if args.get("due_date"):
        body["due_date"] = args["due_date"]
    if args.get("reference"):
        body["reference_number"] = args["reference"]
    data = client.call("POST", f"{_api(conn)}/books/v3/invoices?organization_id={org}&send=false", json_body=body)
    invoice = data.get("invoice") if isinstance(data, dict) and isinstance(data.get("invoice"), dict) else {}
    iid = str(invoice.get("invoice_id") or "")
    domain = DCS.get((conn.config or {}).get("dc") or dc(), "zoho.com")
    url = f"https://books.{domain}/app/{org}#/invoices/{iid}" if ID_RE.match(iid) else ""
    return {"id": iid, "url": url, "title": str(invoice.get("invoice_number") or "Draft invoice")}


def _identify(client, token):
    current = dc()
    domain = str(token.get("api_domain") or "") if isinstance(token, dict) else ""
    host = urllib.parse.urlparse(domain).hostname or ""
    config = {"dc": current, "api_domain": f"https://{host}" if domain.startswith("https://") and host in HOSTS else ""}
    config["books_org_id"] = ""
    try:
        fake = type("C", (), {"config": config})()
        data = client.call("GET", f"{_api(fake)}/books/v3/organizations")
        orgs = data.get("organizations") if isinstance(data, dict) else None
        first = orgs[0] if isinstance(orgs, list) and orgs and isinstance(orgs[0], dict) else {}
        org_id = str(first.get("organization_id") or "")
        config["books_org_id"] = org_id if ID_RE.match(org_id) else ""
    except (WriteError, ValueError):
        pass  # CRM still works without Books
    return f"Zoho ({DCS[current]})", config


def _demo(module):
    def make(args):
        n = str(secrets.randbelow(10**12) + 10**11)
        title = args.get("deal_name") or args.get("last_name") or args.get("customer_name") or "Draft invoice"
        return {"id": n, "url": f"https://zoho.example.com/{module}/{n}", "title": title}

    return make


register(
    Provider(
        key="zoho",
        name="Zoho",
        description="Create Zoho CRM leads and deals, and draft Zoho Books invoices.",
        authorize_url=lambda: f"https://accounts.{DCS[dc()]}/oauth/v2/auth",
        token_url=lambda: f"https://accounts.{DCS[dc()]}/oauth/v2/token",
        base_scopes=("ZohoBooks.settings.READ", "ZohoBooks.invoices.READ"),
        auth_params={"access_type": "offline", "prompt": "consent"},
        scope_separator=",",
        hosts=HOSTS,
        auth_scheme="Zoho-oauthtoken",
        identify=_identify,
        demo_label="Nile Labs Zoho One (demo, simulated)",
        demo_config={"dc": "com", "books_org_id": "700000001"},
        actions=[
            Action(
                "crm_create_lead", "Create a Zoho CRM lead",
                "Create a lead in Zoho CRM. last_name and company are required. Needs approval.",
                obj(
                    {"last_name": text(80, 1), "first_name": text(40), "company": text(200, 1), "email": EMAIL, "phone": text(30), "description": text(8000)},
                    ["last_name", "company"],
                ),
                MEDIUM, ("ZohoCRM.modules.leads.CREATE",), _lead_preview, _lead, _demo("crm/leads"), _lead_checks,
            ),
            Action(
                "crm_create_deal", "Create a Zoho CRM deal",
                "Create a deal in Zoho CRM. amount is a plain number. Needs approval.",
                obj({"deal_name": text(120, 1), "amount": text(16), "stage": text(60), "closing_date": {"type": "string", "format": "date"}}, ["deal_name"]),
                MEDIUM, ("ZohoCRM.modules.deals.CREATE",),
                lambda a, c=None: f"Create Zoho CRM deal “{short(a['deal_name'], 80)}”" + (f" worth {a['amount']}" if a.get("amount") else ""),
                _deal, _demo("crm/deals"), _deal_checks,
            ),
            Action(
                "books_create_invoice", "Draft a Zoho Books invoice",
                "Create a draft invoice in Zoho Books for an existing customer. It is not sent. Needs approval.",
                obj(
                    {
                        "customer_id": text(25, 1),
                        "customer_name": text(120),
                        "line_items": {"type": "array", "items": LINE, "maxItems": 50},
                        "due_date": {"type": "string", "format": "date"},
                        "reference": text(60),
                    },
                    ["customer_id", "line_items"],
                ),
                HIGH, ("ZohoBooks.invoices.CREATE",), _invoice_preview, _invoice, _demo("books/invoices"), _invoice_checks,
            ),
        ],
    )
)
