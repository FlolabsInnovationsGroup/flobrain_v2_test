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
    "ai.usage.view": {"label": "View AI usage", "matrix": "org"},
    "budget.view": {"label": "View AI budgets", "matrix": "org"},
    "budget.manage": {"label": "Manage AI budgets", "matrix": "org"},
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
}

_ADMIN_DEFAULTS = {
    key for key in PERMISSION_CATALOG if not key.startswith("payroll.")
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
