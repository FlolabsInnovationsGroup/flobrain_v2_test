"""HubSpot CRM: create or update a contact, create a deal, log a note."""

import re
import secrets
import urllib.parse

from django.utils import timezone

from integrations.write.registry import EMAIL, MEDIUM, Action, Provider, decimal, obj, register, short, single_line, text

API = "https://api.hubapi.com"
ID_RE = re.compile(r"^\d{1,20}$")
CONTACT_FIELDS = ("firstname", "lastname", "company", "phone", "jobtitle")
CONTACT_PROPS = {name: text(120) for name in CONTACT_FIELDS}


def _record(conn, type_id: str, object_id: str) -> str:
    portal = str((conn.config or {}).get("portal_id") or "")
    if not ID_RE.match(portal) or not ID_RE.match(str(object_id or "")):
        return ""
    return f"https://app.hubspot.com/contacts/{portal}/record/{type_id}/{object_id}"


def _name(args) -> str:
    return " ".join(p for p in (args.get("firstname"), args.get("lastname")) if p).strip()


def _contact_checks(args):
    for name in CONTACT_FIELDS:
        single_line(args.get(name, ""), name)


def _create_preview(args, conn=None):
    who = _name(args)
    company = f" at {args['company']}" if args.get("company") else ""
    return f"Add HubSpot contact {who + ' ' if who else ''}<{args['email']}>{company}"


def _create(client, args, conn):
    props = {"email": args["email"], **{k: args[k] for k in CONTACT_FIELDS if args.get(k)}}
    data = client.call("POST", f"{API}/crm/v3/objects/contacts", json_body={"properties": props})
    cid = str(data.get("id") or "")
    return {"id": cid, "url": _record(conn, "0-1", cid), "title": _name(args) or args["email"]}


def _update_checks(args):
    _contact_checks(args)
    if not any(args.get(k) for k in CONTACT_FIELDS):
        raise ValueError("say what to change: firstname, lastname, company, phone or jobtitle")


def _update(client, args, conn):
    props = {k: args[k] for k in CONTACT_FIELDS if args.get(k)}
    email = urllib.parse.quote(args["email"], safe="")
    data = client.call("PATCH", f"{API}/crm/v3/objects/contacts/{email}?idProperty=email", json_body={"properties": props})
    cid = str(data.get("id") or "")
    return {"id": cid, "url": _record(conn, "0-1", cid), "title": args["email"]}


def _deal_checks(args):
    single_line(args["dealname"], "dealname")
    decimal(args.get("amount"), "amount")


def _deal_preview(args, conn=None):
    amount = f" worth {args['amount']}" if args.get("amount") else ""
    stage = f" at stage {args['dealstage']}" if args.get("dealstage") else ""
    return f"Create HubSpot deal “{short(args['dealname'], 80)}”{amount}{stage}"


def _deal(client, args, conn):
    props = {"dealname": args["dealname"], "pipeline": args.get("pipeline") or "default", "dealstage": args.get("dealstage") or "appointmentscheduled"}
    if args.get("amount"):
        props["amount"] = args["amount"]
    if args.get("closedate"):
        props["closedate"] = args["closedate"]
    data = client.call("POST", f"{API}/crm/v3/objects/deals", json_body={"properties": props})
    did = str(data.get("id") or "")
    return {"id": did, "url": _record(conn, "0-3", did), "title": args["dealname"]}


def _note_checks(args):
    if args.get("contact_id") and not ID_RE.match(args["contact_id"]):
        raise ValueError("contact_id is a HubSpot record number")


def _note_preview(args, conn=None):
    on = args.get("contact_email") or (f"contact {args['contact_id']}" if args.get("contact_id") else "")
    return f"Log a HubSpot note{' on ' + on if on else ''}: “{short(args['body'], 100)}”"


def _note(client, args, conn):
    contact = args.get("contact_id") or ""
    if not contact and args.get("contact_email"):
        email = urllib.parse.quote(args["contact_email"], safe="")
        found = client.call("GET", f"{API}/crm/v3/objects/contacts/{email}?idProperty=email")
        contact = str(found.get("id") or "")
    body = {"properties": {"hs_note_body": args["body"], "hs_timestamp": timezone.now().isoformat()}}
    if contact:
        body["associations"] = [
            {"to": {"id": contact}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}]}
        ]
    data = client.call("POST", f"{API}/crm/v3/objects/notes", json_body=body)
    return {"id": str(data.get("id") or ""), "url": _record(conn, "0-1", contact) if contact else "", "title": "Note"}


def _identify(client, token):
    data = client.call("GET", f"{API}/oauth/v1/access-tokens/{urllib.parse.quote(token, safe='')}")
    if not isinstance(data, dict):
        data = {}
    portal = str(data.get("hub_id") or "")
    return str(data.get("hub_domain") or "HubSpot account")[:160], {"portal_id": portal if ID_RE.match(portal) else ""}


def _demo(type_id):
    def make(args):
        n = str(secrets.randbelow(9_000_000) + 1_000_000)
        title = _name(args) or args.get("email") or args.get("dealname") or "Note"
        return {"id": n, "url": f"https://crm.example.com/hubspot/record/{type_id}/{n}", "title": title}

    return make


register(
    Provider(
        key="hubspot",
        name="HubSpot",
        description="Add and update contacts, create deals and log notes in HubSpot CRM.",
        authorize_url="https://app.hubspot.com/oauth/authorize",
        token_url="https://api.hubapi.com/oauth/v1/token",
        base_scopes=("oauth", "crm.objects.contacts.read"),
        hosts=frozenset({"api.hubapi.com"}),
        identify=_identify,
        demo_label="Nile Labs HubSpot portal (demo, simulated)",
        demo_config={"portal_id": "4400000"},
        actions=[
            Action(
                "create_contact", "Add a HubSpot contact",
                "Create a contact in HubSpot. Needs approval.",
                obj({"email": EMAIL, **CONTACT_PROPS}, ["email"]),
                MEDIUM, ("crm.objects.contacts.write",), _create_preview, _create, _demo("0-1"), _contact_checks,
            ),
            Action(
                "update_contact", "Update a HubSpot contact",
                "Update a HubSpot contact found by email. Needs approval.",
                obj({"email": EMAIL, **CONTACT_PROPS}, ["email"]),
                MEDIUM, ("crm.objects.contacts.write",),
                lambda a, c=None: f"Update HubSpot contact {a['email']}: " + ", ".join(f"{k} → {short(a[k], 40)}" for k in CONTACT_FIELDS if a.get(k)),
                _update, _demo("0-1"), _update_checks,
            ),
            Action(
                "create_deal", "Create a HubSpot deal",
                "Create a deal in HubSpot. amount is a plain number like 12000. Needs approval.",
                obj(
                    {"dealname": text(200, 1), "amount": text(20), "dealstage": text(60), "pipeline": text(60), "closedate": {"type": "string", "format": "date"}},
                    ["dealname"],
                ),
                MEDIUM, ("crm.objects.deals.write",), _deal_preview, _deal, _demo("0-3"), _deal_checks,
            ),
            Action(
                "log_note", "Log a note in HubSpot",
                "Log a note in HubSpot, on a contact found by email or id when given. Needs approval.",
                obj({"body": text(10000, 1), "contact_email": EMAIL, "contact_id": text(20)}, ["body"]),
                MEDIUM, ("crm.objects.contacts.write",), _note_preview, _note, _demo("0-46"), _note_checks,
            ),
        ],
    )
)
