"""Permission keys, matrix rows, and per-role defaults (E6)."""

from organizations.models import OrgMembership

# Phase 0 keys first; later phases add rows here and in ROLE_DEFAULTS.
PERMISSION_CATALOG: dict[str, dict] = {
    "org.members.view": {
        "label": "View organization members",
        "matrix": "org",
    },
    "org.members.manage": {
        "label": "Manage organization members",
        "matrix": "org",
    },
    "org.members.view_contact": {
        "label": "View member contact details",
        "matrix": "org",
    },
    "grants.create": {
        "label": "Create permission grants",
        "matrix": "org",
    },
    "grants.revoke": {
        "label": "Revoke permission grants",
        "matrix": "org",
    },
    "permission_requests.create": {
        "label": "Create permission requests",
        "matrix": "org",
    },
    "permission_requests.decide": {
        "label": "Approve or reject permission requests",
        "matrix": "org",
    },
    "audit.view": {
        "label": "View audit events",
        "matrix": "org",
    },
    "org.view": {"label": "View organization", "matrix": "org"},
    "org.manage_settings": {"label": "Manage organization settings", "matrix": "org"},
    "team.view": {"label": "View team", "matrix": "team"},
    "team.manage": {"label": "Manage team", "matrix": "team"},
    "project.view": {"label": "View project", "matrix": "project"},
    "project.manage": {"label": "Manage project", "matrix": "project"},
    "chat.use": {"label": "Use chat", "matrix": "org"},
    "memory.view": {"label": "View memory", "matrix": "org"},
    "memory.write": {"label": "Write memory", "matrix": "org"},
    "time.view": {"label": "View time entries", "matrix": "team"},
    "time.write": {"label": "Write time entries", "matrix": "team"},
    "task.view": {"label": "View tasks", "matrix": "team"},
    "task.write": {"label": "Write tasks", "matrix": "team"},
    "hr.view": {"label": "View HR records", "matrix": "org"},
    "hr.manage": {"label": "Manage HR records", "matrix": "org"},
    "payroll.view": {"label": "View payroll", "matrix": "org"},
    "payroll.manage": {"label": "Manage payroll", "matrix": "org"},
    "inbox.view": {"label": "View inbox", "matrix": "org"},
    "inbox.act": {"label": "Act on inbox items", "matrix": "org"},
    "mission.view": {"label": "View Mission Control", "matrix": "team"},
    "room.view": {"label": "View rooms", "matrix": "team"},
    "room.manage": {"label": "Manage rooms", "matrix": "org"},
    "announcement.manage": {"label": "Pin announcements", "matrix": "org"},
    "notification.view": {"label": "View notifications", "matrix": "org"},
    "meeting.view": {"label": "View meetings", "matrix": "team"},
    "meeting.manage": {"label": "Manage meetings", "matrix": "team"},
    "docs.view": {"label": "View documents", "matrix": "team"},
    "docs.write": {"label": "Write documents", "matrix": "team"},
    "tools.manage": {"label": "Manage external tools", "matrix": "org"},
    "search.use": {"label": "Use global search", "matrix": "org"},
    "ai.use": {"label": "Use AI", "matrix": "org"},
    "knowledge.ask": {"label": "Ask org knowledge", "matrix": "org"},
    "ai.usage.view": {"label": "View AI usage", "matrix": "org"},
    "budget.view": {"label": "View AI budgets", "matrix": "org"},
    "budget.manage": {"label": "Manage AI budgets", "matrix": "org"},
    "credential.manage": {"label": "Manage org AI keys", "matrix": "org"},
    "buddy.create": {"label": "Create private buddies", "matrix": "org"},
    "buddy.manage": {"label": "Manage and share buddies org-wide", "matrix": "org"},
    "report.generate": {"label": "Generate team reports (leads)", "matrix": "team"},
    "content.use": {"label": "Use Content Studio (own projects)", "matrix": "org"},
    "content.manage": {"label": "Manage all Content Studio projects, brand kits and templates", "matrix": "org"},
    "content.publish": {"label": "Publish or schedule social posts", "matrix": "org"},
    "content.approve": {"label": "Approve social posts", "matrix": "org"},
    "social.connect": {"label": "Connect social accounts", "matrix": "org"},
    "consent.manage": {"label": "Manage the consent registry", "matrix": "org"},
    "webhooks.manage": {"label": "Manage webhooks and API apps", "matrix": "org"},
    "integrations.manage": {"label": "Manage external agents and integrations", "matrix": "org"},
    "incidents.manage": {"label": "Manage the org's incidents", "matrix": "org"},
    "policy.manage": {"label": "Manage the org AI and data policy", "matrix": "org"},
    "billing.view": {"label": "View billing and usage", "matrix": "org"},
    "sso.manage": {"label": "Manage SSO and SCIM", "matrix": "org"},
    "exports.memory": {"label": "Export the org's team and project memory (owner)", "matrix": "org"},
    "marketplace.submit": {"label": "Offer your buddies and templates in the org marketplace", "matrix": "org"},
    "marketplace.manage": {"label": "Approve marketplace listings", "matrix": "org"},
    "learning.manage": {"label": "Manage learning paths, quizzes, mentorships and cohorts", "matrix": "org"},
    "certificates.issue": {"label": "Issue and revoke certificates", "matrix": "org"},
    "pulse.view": {"label": "Use the Pulse console (AI quality, cost, traces, evaluations, routing)", "matrix": "org"},
    "commissions.manage": {"label": "Record commissions and change their amounts and statuses", "matrix": "org"},
    "automations.use": {"label": "Build and run your own automations", "matrix": "org"},
    "automations.manage": {"label": "Manage the organization's automations and their approval rules", "matrix": "org"},
    "channels.manage": {"label": "Connect WhatsApp, Telegram and the website chat", "matrix": "org"},
    "customers.view": {"label": "See customer conversations from the website chat and WhatsApp", "matrix": "org"},
    "customers.reply": {"label": "Reply to customers and take over from the customer buddy", "matrix": "org"},
    "data.use": {"label": "Ask questions about the organization's datasets", "matrix": "org"},
    "data.manage": {"label": "Add, connect and remove datasets", "matrix": "org"},
    "integrations.act": {"label": "Ask buddies to write to connected apps (each write is approved)", "matrix": "org"},
    "packs.install": {"label": "Install industry packs (buddies, automations, rooms)", "matrix": "org"},
}

_MEMBER_DEFAULTS = {
    "org.members.view",
    "permission_requests.create",
    "org.view",
    "team.view",
    "project.view",
    "chat.use",
    "memory.view",
    "time.view",
    "time.write",
    "task.view",
    "task.write",
    "inbox.view",
    "inbox.act",
    "room.view",
    "notification.view",
    "meeting.view",
    "docs.view",
    "docs.write",
    "search.use",
    "chat.use",
    "ai.use",
    "ai.usage.view",
    "knowledge.ask",
    "buddy.create",
    "content.use",
    "marketplace.submit",
    "automations.use",
    "data.use",
    "integrations.act",
    "customers.reply",
}

# Phase 17 review: held only by a real, active owner. Not in admin defaults, never grantable,
# and not covered by the platform-admin bypass (Q42).
OWNER_ONLY_KEYS = frozenset({"exports.memory", "policy.manage", "sso.manage"})

_ADMIN_DEFAULTS = {
    key for key in PERMISSION_CATALOG if not key.startswith("payroll.") and key not in OWNER_ONLY_KEYS
}

ROLE_DEFAULTS: dict[str, frozenset[str]] = {
    OrgMembership.ORG_ROLE_OWNER: frozenset(PERMISSION_CATALOG),
    OrgMembership.ORG_ROLE_ADMIN: frozenset(_ADMIN_DEFAULTS),
    OrgMembership.ORG_ROLE_MEMBER: frozenset(_MEMBER_DEFAULTS),
}

PHASE0_KEYS = (
    "org.members.view",
    "org.members.view_contact",
    "grants.create",
    "grants.revoke",
    "permission_requests.create",
    "permission_requests.decide",
    "audit.view",
)

# Keys with API enforcement in Phases 0–3 (allowed + denied tests).
PHASE_0_TO_3_API_KEYS = PHASE0_KEYS + (
    "org.members.manage",
    "org.view",
    "team.view",
    "team.manage",
    "project.view",
    "project.manage",
    "task.view",
    "task.write",
    "time.view",
    "time.write",
    "chat.use",
    "mission.view",
)

PHASE_4_TO_6_API_KEYS = (
    "room.view",
    "room.manage",
    "announcement.manage",
    "notification.view",
    "meeting.view",
    "meeting.manage",
    "docs.view",
    "docs.write",
    "tools.manage",
    "search.use",
)
