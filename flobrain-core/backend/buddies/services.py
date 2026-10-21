"""Who sees which buddy, and which sources a buddy may read for one viewer (Decision 34).

A buddy never widens access. Retrieval for a buddy is the intersection of:
- what the **viewer** can read right now (``accessible_rooms``, E37), and
- what the buddy is allowed to read (``allowed_sources``).
The creator's access is checked when sources are saved, never used at read time.
"""

import re
import uuid

from django.db.models import Q

from buddies.models import Buddy
from organizations.models import OrgMembership, TeamMembership
from organizations.permissions import can


def _membership(user, org):
    return OrgMembership.objects.filter(org=org, user=user).first()


def is_admin(user, org) -> bool:
    membership = _membership(user, org)
    return bool(
        getattr(user, "is_platform_admin", False)
        or (membership and membership.org_role in {OrgMembership.ORG_ROLE_OWNER, OrgMembership.ORG_ROLE_ADMIN})
    )


def visible_buddies(user, org):
    """Enabled buddies this user may open and chat with."""
    team_ids = TeamMembership.objects.filter(team__org=org, user=user).values("team_id")
    shared = Q(share_status=Buddy.SHARE_APPROVED) | Q(is_builtin=True)
    rule = (
        Q(created_by=user)
        | (Q(visibility=Buddy.VIS_ORG) & shared)
        | (Q(visibility=Buddy.VIS_TEAM) & shared & Q(team_id__in=team_ids))
    )
    if is_admin(user, org):
        rule |= Q(visibility=Buddy.VIS_TEAM) & shared
    return Buddy.objects.filter(org=org, is_enabled=True).filter(rule)


def can_edit(user, org, buddy) -> bool:
    if buddy.is_builtin or buddy.created_by_id is None:
        return can(user, "buddy.manage", org)
    return buddy.created_by_id == user.id or can(user, "buddy.manage", org)


def source_rooms(buddy, user, org):
    """QuerySet of room ids the buddy may read **for this viewer**, or None for no retrieval."""
    from rooms.services import accessible_rooms

    spec = buddy.allowed_sources or {}
    mode = spec.get("mode") or Buddy.SOURCES_NONE
    if mode == Buddy.SOURCES_NONE:
        return None
    rooms = accessible_rooms(user, org)
    if mode == Buddy.SOURCES_ROOMS:
        rooms = rooms.filter(pk__in=[str(r) for r in (spec.get("rooms") or [])])
    elif mode != Buddy.SOURCES_ACCESSIBLE:
        return None
    return rooms.values("pk")


def source_types(buddy) -> list[str]:
    allowed = {"doc", "room_message", "transcript"}
    types = [t for t in ((buddy.allowed_sources or {}).get("source_types") or ["doc", "room_message"]) if t in allowed]
    types = types or ["doc", "room_message"]
    return types + ["summary"] if "transcript" in types else types  # meetings = transcripts and their summaries


# --- Buddy Builder (8b) -------------------------------------------------------

MODEL_RE = re.compile(r"^[A-Za-z0-9._:/@-]{1,128}$")
MAX_PROMPT = 4000
MAX_PRESETS = 10


class BuddyInvalid(Exception):
    pass


def is_team_lead(user, team) -> bool:
    return TeamMembership.objects.filter(team=team, user=user, team_role=TeamMembership.ROLE_LEAD).exists()


def holds_tool(user, org, tool_key) -> bool:
    from actions.registry import TOOLS

    tool = TOOLS.get(tool_key)
    if tool is None:
        return False
    if tool_key == "reports.generate":
        return is_admin(user, org) or TeamMembership.objects.filter(
            team__org=org, user=user, team_role=TeamMembership.ROLE_LEAD
        ).exists()
    return can(user, tool["perm_key"], org)


def clean_definition(user, org, data, partial=False) -> dict:
    """Validate Buddy Builder fields against the **editor's** current access."""
    from rooms.services import accessible_rooms

    out = {}
    if not partial or "name" in data:
        name = str(data.get("name") or "").strip()
        if not name or len(name) > 80:
            raise BuddyInvalid("name is required (at most 80 characters)")
        out["name"] = name
    for field, limit in (("description", 300), ("icon", 40)):
        if field in data:
            out[field] = str(data.get(field) or "")[:limit]
    if "system_prompt" in data:
        prompt = str(data.get("system_prompt") or "")
        if len(prompt) > MAX_PROMPT:
            raise BuddyInvalid(f"system_prompt is longer than {MAX_PROMPT} characters")
        out["system_prompt"] = prompt
    if "preset_prompts" in data:
        presets = data.get("preset_prompts") or []
        if not isinstance(presets, list) or len(presets) > MAX_PRESETS:
            raise BuddyInvalid(f"preset_prompts must be a list of at most {MAX_PRESETS}")
        cleaned = []
        for item in presets:
            if not isinstance(item, dict):
                raise BuddyInvalid("each preset needs a label and a prompt")
            label, prompt = str(item.get("label") or "").strip(), str(item.get("prompt") or "").strip()
            if not label or not prompt or len(label) > 40 or len(prompt) > 1000:
                raise BuddyInvalid("each preset needs a label (40) and a prompt (1000)")
            cleaned.append({"label": label, "prompt": prompt})
        out["preset_prompts"] = cleaned
    if "allowed_sources" in data:
        spec = data.get("allowed_sources") or {}
        if not isinstance(spec, dict):
            raise BuddyInvalid("allowed_sources must be an object")
        mode = spec.get("mode") or Buddy.SOURCES_NONE
        if mode not in (Buddy.SOURCES_NONE, Buddy.SOURCES_ACCESSIBLE, Buddy.SOURCES_ROOMS):
            raise BuddyInvalid("allowed_sources.mode must be none, accessible or rooms")
        types = spec.get("source_types") or ["doc", "room_message"]
        if not isinstance(types, list) or not set(types) <= {"doc", "room_message", "transcript"}:
            raise BuddyInvalid("source_types may contain doc, room_message and transcript")
        cleaned = {"mode": mode, "source_types": list(dict.fromkeys(types))}
        if mode == Buddy.SOURCES_ROOMS:
            rooms = spec.get("rooms") or []
            if not isinstance(rooms, list) or not rooms or len(rooms) > 50:
                raise BuddyInvalid("rooms must list 1 to 50 rooms")
            try:
                ids = [str(uuid.UUID(str(r))) for r in rooms]
            except ValueError as exc:
                raise BuddyInvalid("rooms must be room ids") from exc
            visible = {str(pk) for pk in accessible_rooms(user, org).filter(pk__in=ids).values_list("pk", flat=True)}
            if set(ids) - visible:
                raise BuddyInvalid("you can only add rooms you can read")
            cleaned["rooms"] = list(dict.fromkeys(ids))
        out["allowed_sources"] = cleaned
    if "allowed_tools" in data:
        tools = data.get("allowed_tools") or []
        if not isinstance(tools, list) or len(tools) > 20:
            raise BuddyInvalid("allowed_tools must be a list")
        for key in tools:
            if not holds_tool(user, org, str(key)):
                raise BuddyInvalid(f"you cannot give this buddy the tool {key}")
        out["allowed_tools"] = list(dict.fromkeys(str(k) for k in tools))
    if "default_model" in data:
        model = data.get("default_model")
        if model in (None, ""):
            out["default_model"] = None
        elif not MODEL_RE.match(str(model)):
            raise BuddyInvalid("default_model is not a model name")
        else:
            out["default_model"] = str(model)
    return out


# Changing any of these on a shared buddy sends it back for approval.
REAPPROVAL_FIELDS = {"system_prompt", "allowed_sources", "allowed_tools", "default_model", "preset_prompts"}


def behaviour_hash(buddy) -> str:
    """What an approver approves. Approve must name this hash, so an edit made after the
    approver looked (while the share is pending) cannot be approved by accident."""
    import hashlib
    import json

    body = {
        "system_prompt": buddy.system_prompt,
        "allowed_sources": buddy.allowed_sources,
        "allowed_tools": buddy.allowed_tools,
        "default_model": buddy.default_model,
        "preset_prompts": buddy.preset_prompts,
        "target": buddy.share_target,
        "team": str(buddy.share_team_id or ""),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def can_decide_share(user, org, buddy) -> bool:
    if buddy.share_status != Buddy.SHARE_PENDING:
        return False
    if buddy.share_target == Buddy.VIS_ORG:
        return can(user, "buddy.manage", org)
    if buddy.share_target == Buddy.VIS_TEAM and buddy.share_team_id:
        return can(user, "buddy.manage", org) or is_team_lead(user, buddy.share_team)
    return False
