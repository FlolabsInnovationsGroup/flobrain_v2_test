"""Industry packs (flag ``packs``, permission ``packs.install``).

A pack is a declarative manifest: rooms, buddies (by template key, with a shipped fallback), knowledge
starter documents, workflow templates (by key) and settings (time tracking tags). ``preview`` says
exactly what an install would create and what is skipped because another feature is missing.
``install`` is idempotent and records every object it created in an ``InstalledPack``.
``uninstall`` deletes only objects nobody changed or used since; everything else is kept and listed.

Optional apps are looked up at call time, never imported at module import time:
- buddy templates: ``buddies.templates_extra.TEMPLATES[key]`` (the specialist buddies) or
  ``buddies.templates``, else the fallback shipped here;
- workflows: the ``automations`` app's ``Workflow`` model and ``automations.schema.clean_workflow``. A
  pack workflow uses the Workflows app's own template when its key exists there
  (``automations.templates.build``), else the pack's ``workflow`` spec; either way it is validated like
  any workflow and created switched off. App missing or flag off: "needs Workflows".
"""

import hashlib
import importlib
import json
import logging
import uuid

from django.apps import apps
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

logger = logging.getLogger(__name__)

SAMPLE = "(Starter text from a FloBrain industry pack. Edit it to match how you work.)"

KIND_ORDER = ("room", "doc", "buddy", "automation", "time_tag")

# --- manifests ----------------------------------------------------------------------------------

PACKS = {
    "education": {
        "key": "education",
        "version": 1,
        "name": "Education",
        "summary": "For universities and bootcamps: cohort rooms, a teaching assistant, an admissions buddy, attendance and assignment workflows, and a grading rubric.",
        "audience": "Universities and bootcamps",
        "items": [
            {"key": "room-cohort", "kind": "room", "label": "Spring cohort", "detail": "A room for one cohort's announcements and questions."},
            {"key": "room-teaching", "kind": "room", "label": "Teaching team", "detail": "Where instructors plan sessions and grading."},
            {"key": "room-admissions", "kind": "room", "label": "Admissions", "detail": "Applicant questions and decisions."},
            {
                "key": "doc-rubric",
                "kind": "doc",
                "label": "Grading rubric",
                "room": "room-teaching",
                "detail": "A four-level rubric for projects, in the Teaching team room.",
                "body": (
                    "# Grading rubric\n\n"
                    "Score each criterion from 1 to 4.\n\n"
                    "| Criterion | 4 Excellent | 3 Good | 2 Developing | 1 Missing |\n"
                    "|---|---|---|---|---|\n"
                    "| Understanding | Explains the why and edge cases | Explains the main idea | Repeats steps | Not shown |\n"
                    "| Quality of work | Complete, tested, clean | Complete with small gaps | Partly done | Not submitted |\n"
                    "| Communication | Clear and well structured | Clear | Hard to follow | Missing |\n"
                    "| On time | Early or on time | Up to 1 day late | Up to 3 days late | Later |\n\n"
                    "Pass: 10 points or more, with no criterion at 1.\n\n" + SAMPLE
                ),
            },
            {
                "key": "doc-admissions-faq",
                "kind": "doc",
                "label": "Admissions FAQ",
                "room": "room-admissions",
                "detail": "Questions applicants ask most, for the admissions buddy to answer from.",
                "body": (
                    "# Admissions FAQ\n\n"
                    "**When is the next intake?** Fill in your dates.\n\n"
                    "**What are the entry requirements?** List them here.\n\n"
                    "**How much does it cost, and are there scholarships?** Add fees and scholarship rules.\n\n"
                    "**How long does a decision take?** Usually within 10 working days.\n\n" + SAMPLE
                ),
            },
            {
                "key": "buddy-ta",
                "kind": "buddy",
                "label": "Teaching assistant",
                "template": "teaching_assistant",
                "detail": "Answers learners' questions from course material and drafts feedback using the rubric.",
                "fallback": {
                    "name": "Teaching assistant",
                    "icon": "graduation",
                    "description": "Answers learners' questions from course material and drafts feedback using the rubric.",
                    "system_prompt": (
                        "You are a teaching assistant. Answer from the course material and the grading rubric you can read. "
                        "Guide learners to the answer instead of giving full solutions to graded work. "
                        "When drafting feedback, use the rubric's criteria and be kind and specific. "
                        "Reply in the learner's language."
                    ),
                    "preset_prompts": [
                        {"label": "Explain a topic", "prompt": "Explain this topic simply, with one example."},
                        {"label": "Draft feedback", "prompt": "Draft feedback on this submission using the grading rubric."},
                    ],
                    "allowed_sources": {"mode": "accessible", "source_types": ["doc", "room_message"]},
                    "allowed_tools": [],
                },
            },
            {
                "key": "buddy-admissions",
                "kind": "buddy",
                "label": "Admissions buddy",
                "template": "admissions",
                "detail": "Answers applicant questions from the admissions FAQ and drafts replies for a person to send.",
                "fallback": {
                    "name": "Admissions buddy",
                    "icon": "mail",
                    "description": "Answers applicant questions from the admissions FAQ and drafts replies for a person to send.",
                    "system_prompt": (
                        "You help the admissions team answer applicants. Use only the admissions FAQ and documents you can read. "
                        "Never promise admission, a scholarship or a price that is not written down. "
                        "Draft replies for a person to review and send. Reply in the applicant's language."
                    ),
                    "preset_prompts": [{"label": "Draft a reply", "prompt": "Draft a reply to this applicant's question."}],
                    "allowed_sources": {"mode": "accessible", "source_types": ["doc"]},
                    "allowed_tools": [],
                },
            },
            {
                "key": "auto-attendance",
                "kind": "automation",
                "label": "Attendance reminder",
                "template": "attendance_reminder",
                "room": "room-cohort",
                "detail": "Before each session, reminds the cohort and asks instructors to mark attendance. Created switched off.",
                "requires": [{"flag": "automations", "label": "Workflows"}],
                "workflow": {
                    "description": "Every Monday at 08:30, reminds the cohort about this week's sessions and asks instructors to mark attendance.",
                    "trigger": {"type": "schedule", "every": "week", "weekday": 0, "at": "08:30"},
                    "steps": [
                        {"type": "post_to_room", "room": "{room}", "text": "Sessions this week: please join on time. Instructors, mark attendance after each session."},
                    ],
                },
            },
            {
                "key": "auto-assignments",
                "kind": "automation",
                "label": "Assignment due reminder",
                "template": "assignment_due_reminder",
                "room": "room-cohort",
                "detail": "Two days before an assignment is due, posts a reminder. Created switched off.",
                "requires": [{"flag": "automations", "label": "Workflows"}],
                "workflow": {
                    "description": "Every Wednesday at 09:00, lists the cohort's tasks due soon and posts a reminder in the cohort room.",
                    "trigger": {"type": "schedule", "every": "week", "weekday": 2, "at": "09:00"},
                    "steps": [
                        {"type": "ai_prompt", "label": "List what is due", "context": "recent_tasks", "room": "{room}",
                         "prompt": "List the assignments due in the next two days, with their due dates. Short and friendly."},
                        {"type": "post_to_room", "room": "{room}", "text": "Due soon\n\n{{steps.1.output}}"},
                    ],
                },
            },
            {"key": "tags-education", "kind": "time_tag", "label": "Time tags", "names": ["Teaching", "Grading", "Admissions"], "detail": "Teaching, Grading and Admissions, for logging hours."},
        ],
    },
    "smb": {
        "key": "smb",
        "version": 1,
        "name": "Small business",
        "summary": "Sales, finance and customer buddies, an invoice follow-up workflow, and a checklist for your WhatsApp customer buddy.",
        "audience": "Small and medium businesses",
        "items": [
            {"key": "room-sales", "kind": "room", "label": "Sales", "detail": "Leads, quotes and wins."},
            {"key": "room-finance", "kind": "room", "label": "Finance", "detail": "Invoices, payments and costs."},
            {"key": "room-customers", "kind": "room", "label": "Customer care", "detail": "Customer questions and hand-offs."},
            {
                "key": "doc-invoice-policy",
                "kind": "doc",
                "label": "Invoice follow-up policy",
                "room": "room-finance",
                "detail": "When and how to remind customers about unpaid invoices.",
                "body": (
                    "# Invoice follow-up policy\n\n"
                    "1. **3 days after the due date:** a friendly reminder with the invoice attached.\n"
                    "2. **10 days after:** a second reminder and a phone call.\n"
                    "3. **30 days after:** the owner decides on next steps.\n\n"
                    "Never threaten, never add fees that are not in the contract, and always thank the customer.\n\n" + SAMPLE
                ),
            },
            {
                "key": "doc-whatsapp-checklist",
                "kind": "doc",
                "label": "WhatsApp customer buddy setup checklist",
                "room": "room-customers",
                "detail": "Steps to put a customer buddy on WhatsApp safely.",
                "requires": [{"flag": "channels", "label": "Channels"}],
                "body": (
                    "# WhatsApp customer buddy: setup checklist\n\n"
                    "- [ ] A Meta business account, verified.\n"
                    "- [ ] A phone number for WhatsApp Business that is not used in the WhatsApp app.\n"
                    "- [ ] An admin connects WhatsApp in Settings, Channels.\n"
                    "- [ ] Write the answers the buddy may give: opening hours, prices, delivery, returns.\n"
                    "- [ ] Decide when it hands over to a person (complaints, refunds, anything it is unsure about).\n"
                    "- [ ] Pick who gets hand-offs and test with your own phone first.\n"
                    "- [ ] Tell customers they are talking to an assistant.\n\n" + SAMPLE
                ),
            },
            {
                "key": "buddy-sales",
                "kind": "buddy",
                "label": "Sales buddy",
                "template": "sales",
                "detail": "Drafts follow-ups and quotes, and prepares you for calls.",
                "fallback": {
                    "name": "Sales buddy",
                    "icon": "target",
                    "description": "Drafts follow-ups and quotes, and prepares you for calls.",
                    "system_prompt": (
                        "You help the sales team. Draft short follow-up messages and quotes, and prepare call notes from what "
                        "you can read. Never invent prices or discounts; ask for them. Proposed tasks wait for approval."
                    ),
                    "preset_prompts": [
                        {"label": "Follow-up", "prompt": "Draft a short follow-up to this lead."},
                        {"label": "Call prep", "prompt": "Prepare me for a call with this customer."},
                    ],
                    "allowed_sources": {"mode": "accessible", "source_types": ["doc", "room_message"]},
                    "allowed_tools": ["tasks.create"],
                },
            },
            {
                "key": "buddy-finance",
                "kind": "buddy",
                "label": "Finance buddy",
                "template": "finance",
                "detail": "Explains costs and invoices and drafts payment reminders that follow your policy.",
                "fallback": {
                    "name": "Finance buddy",
                    "icon": "wallet",
                    "description": "Explains costs and invoices and drafts payment reminders that follow your policy.",
                    "system_prompt": (
                        "You help with invoices, payments and costs. Follow the invoice follow-up policy. "
                        "Never invent figures; ask for the numbers. Draft reminders for a person to send."
                    ),
                    "preset_prompts": [{"label": "Payment reminder", "prompt": "Draft a polite reminder for this unpaid invoice."}],
                    "allowed_sources": {"mode": "accessible", "source_types": ["doc"]},
                    "allowed_tools": [],
                },
            },
            {
                "key": "buddy-customer",
                "kind": "buddy",
                "label": "Customer buddy",
                "template": "customer",
                "detail": "Drafts answers to customer questions from your documents, for a person to check.",
                "fallback": {
                    "name": "Customer buddy",
                    "icon": "message",
                    "description": "Drafts answers to customer questions from your documents, for a person to check.",
                    "system_prompt": (
                        "You draft answers to customer questions from the documents you can read. Be warm and short. "
                        "If you are unsure, or the customer is upset or asks for a refund, say a person will follow up."
                    ),
                    "preset_prompts": [{"label": "Draft an answer", "prompt": "Draft an answer to this customer message."}],
                    "allowed_sources": {"mode": "accessible", "source_types": ["doc"]},
                    "allowed_tools": [],
                },
            },
            {
                "key": "auto-invoices",
                "kind": "automation",
                "label": "Invoice follow-up",
                "template": "invoice_follow_up",
                "room": "room-finance",
                "detail": "Finds unpaid invoices past their due date and drafts reminders for approval. Created switched off.",
                "requires": [{"flag": "automations", "label": "Workflows"}],
                "workflow": {
                    "description": "Every Monday at 09:00, drafts reminders for overdue invoices, following the invoice follow-up policy, and asks for approval before posting them.",
                    "trigger": {"type": "schedule", "every": "week", "weekday": 0, "at": "09:00"},
                    "steps": [
                        {"type": "ai_prompt", "label": "Draft reminders", "context": "overdue_tasks", "room": "{room}",
                         "prompt": "For each overdue invoice task, draft a short, polite payment reminder that follows the invoice follow-up policy. Never add fees."},
                        {"type": "wait_for_approval", "message": "Check the reminder drafts before they are posted."},
                        {"type": "post_to_room", "room": "{room}", "text": "Invoice reminders to send\n\n{{steps.1.output}}"},
                    ],
                },
            },
        ],
    },
    "agency": {
        "key": "agency",
        "version": 1,
        "name": "Agency",
        "summary": "Client rooms, a project buddy, a weekly client report workflow, and time tracking set up for client work.",
        "audience": "Agencies and studios",
        "items": [
            {"key": "room-client", "kind": "room", "label": "Client: Example Co", "detail": "One room per client. Rename it for your first client."},
            {"key": "room-studio", "kind": "room", "label": "Studio", "detail": "Internal planning across clients."},
            {
                "key": "doc-client-report",
                "kind": "doc",
                "label": "Weekly client report template",
                "room": "room-client",
                "detail": "The shape of the weekly report the workflow drafts.",
                "body": (
                    "# Weekly client report\n\n"
                    "**Done this week:** the main deliverables.\n\n"
                    "**Next week:** what we will deliver.\n\n"
                    "**Waiting on you:** approvals or content we need.\n\n"
                    "**Hours used:** this week and this month, against the budget.\n\n" + SAMPLE
                ),
            },
            {
                "key": "doc-time-guide",
                "kind": "doc",
                "label": "Time tracking guide",
                "room": "room-studio",
                "detail": "How the team logs hours by client.",
                "body": (
                    "# Time tracking guide\n\n"
                    "- Log time daily, against the client's project.\n"
                    "- Tag it: **Client work**, **Internal** or **Pitching**.\n"
                    "- Write one line on what you did; the weekly report uses it.\n\n" + SAMPLE
                ),
            },
            {
                "key": "buddy-project",
                "kind": "buddy",
                "label": "Project buddy",
                "template": "project",
                "detail": "Plans client work, drafts status updates and proposes tasks for approval.",
                "fallback": {
                    "name": "Project buddy",
                    "icon": "kanban",
                    "description": "Plans client work, drafts status updates and proposes tasks for approval.",
                    "system_prompt": (
                        "You help run client projects. Plan work, draft status updates in the weekly report's shape, and "
                        "propose tasks. Never claim a task was created unless it was approved."
                    ),
                    "preset_prompts": [
                        {"label": "Status update", "prompt": "Draft this week's status update for the client."},
                        {"label": "Plan next week", "prompt": "Plan next week's work for this client."},
                    ],
                    "allowed_sources": {"mode": "accessible", "source_types": ["doc", "room_message"]},
                    "allowed_tools": ["tasks.create"],
                },
            },
            {
                "key": "auto-client-report",
                "kind": "automation",
                "label": "Weekly client report",
                "template": "weekly_client_report",
                "room": "room-client",
                "detail": "Every Friday, drafts the client report from finished tasks and logged hours, for approval. Created switched off.",
                "requires": [{"flag": "automations", "label": "Workflows"}],
                "workflow": {
                    "description": "Every Friday at 15:00, drafts the weekly client report from this week's work and waits for approval before posting it.",
                    "trigger": {"type": "schedule", "every": "week", "weekday": 4, "at": "15:00"},
                    "steps": [
                        {"type": "ai_prompt", "label": "Draft the report", "context": "recent_tasks", "room": "{room}",
                         "prompt": "Draft the weekly client report: done this week, next week, waiting on the client, hours used. Use the report template's shape."},
                        {"type": "wait_for_approval", "message": "Check the client report before it is posted."},
                        {"type": "post_to_room", "room": "{room}", "text": "Weekly client report (draft)\n\n{{steps.1.output}}"},
                    ],
                },
            },
            {"key": "tags-agency", "kind": "time_tag", "label": "Time tags", "names": ["Client work", "Internal", "Pitching"], "detail": "Client work, Internal and Pitching, for logging hours by type of work."},
        ],
    },
}


def items_of(pack) -> list[dict]:
    return sorted(pack["items"], key=lambda i: KIND_ORDER.index(i["kind"]))


# --- optional apps, resolved at call time ------------------------------------------------------


def _optional(module_name):
    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None


BUDDY_TEMPLATE_MODULES = ("buddies.templates_extra", "buddies.templates")


def buddy_template(key):
    """A buddy definition another app ships for ``key`` (the specialist buddies), or None."""
    if not key:
        return None
    for name in BUDDY_TEMPLATE_MODULES:
        module = _optional(name)
        if module is None:
            continue
        try:
            getter = getattr(module, "get_template", None)
            templates = getattr(module, "TEMPLATES", None)
            found = getter(key) if callable(getter) else (templates.get(key) if isinstance(templates, dict) else None)
        except Exception:
            logger.exception("buddy template lookup failed")
            continue
        if isinstance(found, dict):
            return dict(found)
    return None


def workflow_backend():
    """``(Workflow model, clean_workflow)`` from the Workflows app, or None when it isn't there."""
    schema = _optional("automations.schema")
    clean = getattr(schema, "clean_workflow", None) if schema is not None else None
    try:
        model = apps.get_model("automations", "Workflow")
    except (LookupError, ValueError):
        return None
    return (model, clean) if callable(clean) else None


def workflow_definition(item, room_id) -> dict:
    """The Workflows app's own template for this key when it has one, else the pack's spec, with the room filled in."""
    templates = _optional("automations.templates")
    by_key = getattr(templates, "BY_KEY", None) if templates is not None else None
    build = getattr(templates, "build", None) if templates is not None else None
    if isinstance(by_key, dict) and item.get("template") in by_key and callable(build):
        built = build(item["template"], room=room_id)
        return {**built, "template_key": item["template"]}
    spec = json.loads(json.dumps(item["workflow"]).replace('"{room}"', json.dumps(str(room_id or ""))))
    return {"name": item["label"], "template_key": "", **spec}


# --- fingerprints and "untouched" ---------------------------------------------------------------

VOLATILE = {"updated_at", "last_run_at", "next_run_at", "run_count", "last_read_at", "last_error", "last_status", "position"}
DERIVED_MODELS = {"knowledge.knowledgechunk"}  # search index rows rebuilt from the source; not a sign of use


def label_of(obj) -> str:
    return f"{obj._meta.app_label}.{obj._meta.model_name}"


def fingerprint(obj) -> str:
    data = {}
    for field in obj._meta.concrete_fields:
        if field.attname in VOLATILE or getattr(field, "auto_now", False):
            continue
        data[field.attname] = getattr(obj, field.attname)
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _references(obj, allowed) -> int:
    """Rows elsewhere that point at ``obj``, except derived index rows and ``allowed(model_label, row_qs)``."""
    total = 0
    for rel in obj._meta.related_objects:
        model = rel.related_model
        name = label_of(model) if hasattr(model, "_meta") else ""
        if name in DERIVED_MODELS:
            continue
        try:
            qs = model._base_manager.filter(**{rel.field.name: obj})
        except Exception:
            continue
        qs = allowed(name, qs)
        total += qs.count()
    return total


def _load(item):
    try:
        model = apps.get_model(item["model"])
    except (LookupError, ValueError, KeyError):
        return None
    return model._base_manager.filter(pk=item.get("id")).first()


# --- preview ------------------------------------------------------------------------------------


def _membership(org, user):
    from organizations.models import OrgMembership

    return OrgMembership.objects.filter(org=org, user=user).first()


def _needs(org, membership, item) -> str:
    """Empty when the item can be created now, else the name of the missing feature."""
    from organizations.flags import effective_flag

    for req in item.get("requires") or []:
        if req.get("flag") and not effective_flag(org, membership, req["flag"], default=False):
            return req.get("label") or req["flag"]
    if item["kind"] == "buddy" and not effective_flag(org, membership, "buddies", default=False):
        return "Buddies"
    if item["kind"] == "automation":
        from organizations.permissions.engine import can

        if workflow_backend() is None:
            return "Workflows"
        if not can(membership.user if membership else None, "automations.manage", org):
            return "Permission to manage workflows"
    return ""


def active_install(org, pack_key):
    from growth.models import InstalledPack

    return InstalledPack.objects.filter(org=org, pack=pack_key, status=InstalledPack.INSTALLED).first()


def preview(org, user, pack) -> dict:
    membership = _membership(org, user)
    installed = active_install(org, pack["key"])
    created = {}
    for entry in installed.items if installed else []:
        created.setdefault(base_key(entry), []).append(entry)
    rows = []
    for item in items_of(pack):
        row = {"key": item["key"], "kind": item["kind"], "label": item["label"], "detail": item.get("detail", ""), "needs": ""}
        if item["key"] in created:
            entries = created[item["key"]]
            present = any(not e.get("model") or _load(e) is not None for e in entries)
            row["action"] = "installed" if present else "removed"
        else:
            needs = _needs(org, membership, item)
            row["action"] = "skip" if needs else "create"
            row["needs"] = needs
            if item["kind"] == "buddy" and not needs:
                row["from_template"] = buddy_template(item.get("template")) is not None
        rows.append(row)
    counts = {a: sum(1 for r in rows if r["action"] == a) for a in ("create", "skip", "installed", "removed")}
    return {"pack": pack_summary(pack, installed), "items": rows, "counts": counts}


def pack_summary(pack, installed=None) -> dict:
    kinds = {}
    for item in pack["items"]:
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    return {
        "key": pack["key"],
        "name": pack["name"],
        "summary": pack["summary"],
        "audience": pack["audience"],
        "version": pack["version"],
        "counts": kinds,
        "installed": installed is not None,
        "installed_at": installed.installed_at.isoformat() if installed else None,
        "installed_by": str(installed.installed_by_id) if installed and installed.installed_by_id else None,
    }


# --- install ------------------------------------------------------------------------------------


class _Ctx:
    def __init__(self, org, user, pack, record):
        self.org, self.user, self.pack, self.record = org, user, pack, record
        self.objects = {}  # item key -> created or existing object
        for entry in record.items:
            obj = _load(entry)
            if obj is not None:
                self.objects[entry["key"]] = obj


def _make_room(ctx, item):
    from rooms.models import Room, RoomMember

    room = Room.objects.create(org=ctx.org, name=item["label"][:200], kind=Room.KIND_GROUP)
    RoomMember.objects.create(room=room, user=ctx.user)
    return room


def _make_doc(ctx, item):
    from docs_app.models import Document

    room = ctx.objects.get(item.get("room"))
    if room is None:
        raise _Skip("Rooms")
    return Document.objects.create(org=ctx.org, room=room, title=item["label"][:200], content_text=item["body"], created_by=ctx.user)


def _make_buddy(ctx, item):
    from buddies.models import Buddy
    from buddies.services import BuddyInvalid, clean_definition, holds_tool

    definition = dict(item.get("fallback") or {})
    definition.update(buddy_template(item.get("template")) or {})
    definition["allowed_tools"] = [t for t in definition.get("allowed_tools") or [] if holds_tool(ctx.user, ctx.org, str(t))]
    keys = ("name", "description", "icon", "system_prompt", "preset_prompts", "allowed_sources", "allowed_tools", "default_model")
    try:
        fields = clean_definition(ctx.user, ctx.org, {k: definition[k] for k in keys if k in definition})
    except BuddyInvalid as exc:
        raise _Skip("Buddies") from exc
    if Buddy.objects.filter(org=ctx.org, name__iexact=fields.get("name", "")).exists():
        return []  # the org already has a buddy with this name (e.g. installed from Templates): keep it, never duplicate
    base = f"pack-{ctx.pack['key']}-{slugify(item['key'])}"[:68]
    slug = base if not Buddy.objects.filter(org=ctx.org, slug=base).exists() else f"{base}-{uuid.uuid4().hex[:8]}"
    # The installer holds packs.install (an admin permission) and saw this exact definition in the preview.
    return Buddy.objects.create(
        org=ctx.org,
        slug=slug,
        created_by=ctx.user,
        visibility=Buddy.VIS_ORG,
        share_status=Buddy.SHARE_APPROVED,
        share_target=Buddy.VIS_ORG,
        share_decided_by=ctx.user,
        **fields,
    )


def _make_automation(ctx, item):
    """Validated like any workflow (rooms must be ones the installer can use) and created switched off:
    nothing runs, posts or sends until someone turns it on."""
    backend = workflow_backend()
    if backend is None:
        raise _Skip("Workflows")
    model, clean = backend
    room = ctx.objects.get(item.get("room"))
    data = workflow_definition(item, room.pk if room is not None else None)
    try:
        trigger, steps = clean(ctx.org, ctx.user, {"trigger": data["trigger"], "steps": data["steps"]})
    except ValueError as exc:  # WorkflowError is a ValueError
        logger.warning("pack workflow %s did not validate: %s", item["key"], exc)
        raise _Skip("Workflows") from exc
    return model.objects.create(
        org=ctx.org,
        name=str(data.get("name") or item["label"])[:120],
        description=str(data.get("description") or "")[:500],
        enabled=False,
        created_by=ctx.user,
        run_as=ctx.user,
        trigger=trigger,
        trigger_type=trigger.get("type", "manual"),
        steps=steps,
        template_key=str(data.get("template_key") or "")[:64],
    )


def _make_tags(ctx, item):
    from timetracking.models import Tag

    made = []
    for name in item["names"]:
        tag, created = Tag.objects.get_or_create(org=ctx.org, name=name[:80])
        if created:
            made.append(tag)
    return made  # a list: tags that already existed are not ours to remove later


MAKERS = {"room": _make_room, "doc": _make_doc, "buddy": _make_buddy, "automation": _make_automation, "time_tag": _make_tags}


class _Skip(Exception):
    def __init__(self, needs):
        super().__init__(needs)
        self.needs = needs


def base_key(entry) -> str:
    return entry["key"].split("#", 1)[0]


def _entries(item, result) -> list[dict]:
    """Record entries for what one item created. A list result (time tags) gets ``key#n`` keys, and a
    marker with no model when every tag already existed, so the item still counts as done."""
    head = {"kind": item["kind"], "label": item["label"]}
    if not isinstance(result, list):
        return [{**head, "key": item["key"], "model": label_of(result), "id": str(result.pk), "fingerprint": fingerprint(result)}]
    if not result:
        return [{**head, "key": f"{item['key']}#none", "model": "", "id": "", "fingerprint": ""}]
    return [
        {**head, "key": f"{item['key']}#{n}", "label": f"{item['label']}: {getattr(obj, 'name', obj)}", "model": label_of(obj), "id": str(obj.pk), "fingerprint": fingerprint(obj)}
        for n, obj in enumerate(result)
    ]


def install(org, user, pack) -> tuple:
    """Create what is missing. Returns ``(record, created_entries, skipped, first_install)``."""
    from growth.models import InstalledPack
    from organizations.models import Organization

    membership = _membership(org, user)
    with transaction.atomic():
        Organization.objects.select_for_update().filter(pk=org.pk).first()  # one install at a time per org
        record = active_install(org, pack["key"])
        first = record is None
        if first:
            record = InstalledPack.objects.create(org=org, pack=pack["key"], version=pack["version"], installed_by=user, items=[])
        done = {base_key(e) for e in record.items}
        ctx = _Ctx(org, user, pack, record)
        created, skipped = [], []
        for item in items_of(pack):
            if item["key"] in done:
                continue
            needs = _needs(org, membership, item)
            if needs:
                skipped.append({"key": item["key"], "kind": item["kind"], "label": item["label"], "needs": needs})
                continue
            try:
                with transaction.atomic():
                    result = MAKERS[item["kind"]](ctx, item)
            except _Skip as exc:
                skipped.append({"key": item["key"], "kind": item["kind"], "label": item["label"], "needs": exc.needs})
                continue
            except Exception:
                logger.exception("pack item %s failed", item["key"])
                skipped.append({"key": item["key"], "kind": item["kind"], "label": item["label"], "needs": "error"})
                continue
            created.extend(_entries(item, result))
            if not isinstance(result, list):
                ctx.objects[item["key"]] = result
        record.items = list(record.items) + created
        record.skipped = skipped
        record.save(update_fields=["items", "skipped"])
    return record, [c for c in created if c["model"]], skipped, first


# --- uninstall ----------------------------------------------------------------------------------


def _untouched(entry, obj, record) -> str:
    """Empty when ``obj`` can be removed, else why it is kept: ``changed`` (its fields differ from
    right after install) or ``in_use`` (something else points at it: messages, other documents,
    members besides the installer, chats, pins, time entries, a kept workflow...)."""
    if fingerprint(obj) != entry["fingerprint"]:
        return "changed"
    installer = record.installed_by_id

    def allowed(name, qs):
        if name == "rooms.roommember":
            return qs.exclude(user_id=installer)
        return qs

    if _references(obj, allowed):
        return "in_use"
    return ""


UNINSTALL_ORDER = ("doc", "automation", "buddy", "time_tag", "room")


def uninstall(org, user, record) -> dict:
    removed, kept = [], []
    with transaction.atomic():
        entries = [e for e in record.items if e.get("model")]
        entries.sort(key=lambda e: UNINSTALL_ORDER.index(e["kind"]) if e["kind"] in UNINSTALL_ORDER else 99)
        alive = {}
        for entry in entries:
            obj = _load(entry)
            if obj is not None:
                alive[entry["key"]] = obj
        for entry in entries:
            obj = alive.get(entry["key"])
            row = {"key": entry["key"], "kind": entry["kind"], "label": entry["label"]}
            if obj is None:
                continue  # someone already removed it
            # Documents go first, so a room is removable once its pack documents are gone; a kept one keeps the room.
            reason = _untouched(entry, obj, record)
            if reason:
                kept.append({**row, "reason": reason})
                continue
            obj.delete()
            removed.append(row)
        record.status = record.UNINSTALLED
        record.uninstalled_by = user
        record.uninstalled_at = timezone.now()
        record.kept = kept
        record.save(update_fields=["status", "uninstalled_by", "uninstalled_at", "kept"])
    return {"removed": removed, "kept": kept}
