"""Buddies and buddy threads (Phase 8a).

Checks: active member (403) → ``ai.use`` (403) → flag ``buddies`` (501) →
buddy visible to me (404) → own thread (404). Sends go through ``direct``
only (platform key or the user's BYOK key); never ``multimodal_legacy``.
"""

from django.conf import settings
import uuid

from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from brain.models import Chat
from brain.throttles import AISendThrottle
from buddies.models import Buddy, BuddyPin
from buddies.services import (
    REAPPROVAL_FIELDS,
    BuddyInvalid,
    behaviour_hash,
    can_decide_share,
    can_edit,
    clean_definition,
    is_team_lead,
    visible_buddies,
)
from core_v2.throttles import V2UserThrottle
from core_v2.views import V2APIView
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from organizations.permissions import HasPerm, IsActiveOrgMember, can
from organizations.services.core import audit

FLAG = "buddies"


def _gate(request, view, org_id):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    HasPerm("ai.use").has_permission(request, view)
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, FLAG, default=False):
        return org, Response({"error": "not_implemented", "details": "Buddies are not enabled"}, status=501)
    return org, None


def buddy_payload(buddy, pin=None, user=None):
    data = {
        "id": str(buddy.id),
        "slug": buddy.slug,
        "name": buddy.name,
        "description": buddy.description,
        "icon": buddy.icon,
        "preset_prompts": buddy.preset_prompts or [],
        "allowed_tools": buddy.allowed_tools or [],
        "sources": (buddy.allowed_sources or {}).get("mode", Buddy.SOURCES_NONE),
        "visibility": buddy.visibility,
        "team": str(buddy.team_id) if buddy.team_id else None,
        "share_status": buddy.share_status,
        "builtin": buddy.is_builtin,
        "mine": bool(user and buddy.created_by_id == user.id),
        "pinned": pin is not None,
        "pin_position": pin.position if pin is not None else None,
    }
    return data


def _thread_payload(chat, usage=None, extra=None):
    data = {
        "id": chat.id,
        "title": chat.title,
        "buddy": str(chat.buddy_id),
        "messages": [{"id": row.id, "role": row.role, "text": row.text} for row in chat.messages.order_by("created_at", "id")],
    }
    from buddies.router import answered_by, is_flo

    if is_flo(chat.buddy):
        data["answered_by"] = answered_by(chat)  # W5: which buddy wrote each Flo reply
    if usage is not None:
        data["usage"] = usage
    if extra:
        data.update(extra)
    return data


def _invalid(exc):
    return Response({"error": "invalid", "details": str(exc)}, status=400)


def _flo_hidden(request, org, buddy) -> bool:
    """W5: Flo exists only while ``flo_router`` is on for this person."""
    from buddies.router import flo_on, is_flo

    return is_flo(buddy) and not flo_on(org, request.user)


def _full_payload(buddy, user):
    """Builder view: includes the prompt and sources. Only for people who can edit the buddy."""
    data = buddy_payload(buddy, None, user)
    data.update(
        {
            "system_prompt": buddy.system_prompt,
            "allowed_sources": buddy.allowed_sources or {},
            "default_model": buddy.default_model,
            "share_target": buddy.share_target,
            "share_team": str(buddy.share_team_id) if buddy.share_team_id else None,
        }
    )
    return data


class BuddyListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Create a private buddy (Buddy Builder)")
    def post(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        HasPerm("buddy.create").has_permission(request, self)
        try:
            fields = clean_definition(request.user, org, request.data or {})
        except BuddyInvalid as exc:
            return _invalid(exc)
        slug = f"{slugify(fields['name'])[:60] or 'buddy'}-{uuid.uuid4().hex[:8]}"
        buddy = Buddy.objects.create(org=org, slug=slug, created_by=request.user, **fields)
        audit(request.user, "buddy.create", target=buddy, request=request, org=org)
        return Response(_full_payload(buddy, request.user), status=201)

    @extend_schema(summary="Buddies you can use, with your pins")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        pins = {pin.buddy_id: pin for pin in BuddyPin.objects.filter(user=request.user, buddy__org=org)}
        from buddies.router import flo_on
        from buddies.templates_extra import FLO_SLUG, ensure_flo

        rows = visible_buddies(request.user, org)
        if flo_on(org, request.user):
            ensure_flo(org)  # W5: Flo appears the first time the flag is on
        else:
            rows = rows.exclude(slug=FLO_SLUG, is_builtin=True)
        data = [buddy_payload(b, pins.get(b.id), request.user) for b in rows]
        data.sort(key=lambda d: (not d["pinned"], d["pin_position"] or 0))
        return Response(data)


class BuddyPinView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Replace your pinned buddies (ordered list of ids)")
    def put(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        ids = (request.data or {}).get("buddies")
        if not isinstance(ids, list) or len(ids) > 50:
            return Response({"error": "invalid", "details": "buddies must be a list of at most 50 ids"}, status=400)
        visible = {str(b.id): b for b in visible_buddies(request.user, org)}
        unknown = [i for i in ids if str(i) not in visible]
        if unknown:
            return Response({"error": "not_found", "details": "Unknown buddy"}, status=404)
        ordered = list(dict.fromkeys(str(i) for i in ids))
        BuddyPin.objects.filter(user=request.user, buddy__org=org).delete()
        for position, buddy_id in enumerate(ordered):
            BuddyPin.objects.create(user=request.user, buddy=visible[buddy_id], position=position)
        return Response({"buddies": ordered})


class BuddyThreadListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def _buddy(self, request, org, buddy_id):
        buddy = visible_buddies(request.user, org).filter(pk=buddy_id).first()
        return None if buddy is not None and _flo_hidden(request, org, buddy) else buddy

    @extend_schema(summary="Your threads with a buddy")
    def get(self, request, org_id, buddy_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        buddy = self._buddy(request, org, buddy_id)
        if buddy is None:
            return Response({"error": "not_found", "details": "Buddy not found"}, status=404)
        rows = Chat.objects.filter(org=org, user=request.user, buddy=buddy).order_by("-updated_at")
        return Response([{"id": row.id, "title": row.title, "updated_at": row.updated_at.isoformat()} for row in rows])

    @extend_schema(summary="Start a thread with a buddy")
    def post(self, request, org_id, buddy_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        buddy = self._buddy(request, org, buddy_id)
        if buddy is None:
            return Response({"error": "not_found", "details": "Buddy not found"}, status=404)
        title = str((request.data or {}).get("title") or buddy.name)[:255]
        chat = Chat.objects.create(user=request.user, org=org, buddy=buddy, title=title)
        return Response(_thread_payload(chat), status=201)


def _own_buddy_thread(request, org, thread_id):
    chat = Chat.objects.filter(pk=thread_id, org=org, user=request.user, buddy__isnull=False).select_related("buddy").first()
    if chat is None:
        return None
    # The buddy must still be visible to me (unshared, disabled or deleted buddies close their threads).
    if not visible_buddies(request.user, org).filter(pk=chat.buddy_id).exists():
        return None
    if _flo_hidden(request, org, chat.buddy):
        return None
    return chat


class BuddyThreadDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Read one of your buddy threads")
    def get(self, request, org_id, thread_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        chat = _own_buddy_thread(request, org, thread_id)
        if chat is None:
            return Response({"error": "not_found", "details": "Thread not found"}, status=404)
        return Response(_thread_payload(chat))


class BuddyThreadSendView(V2APIView):
    permission_classes = [IsActiveOrgMember]
    throttle_classes = [V2UserThrottle, AISendThrottle]

    @extend_schema(summary="Send to a buddy thread")
    def post(self, request, org_id, thread_id):
        from buddies.chat import run_buddy_turn

        org, error = _gate(request, self, org_id)
        if error:
            return error
        chat = _own_buddy_thread(request, org, thread_id)
        if chat is None:
            return Response({"error": "not_found", "details": "Thread not found"}, status=404)
        text = ((request.data or {}).get("text") or "").strip()
        if not text:
            return Response({"error": "invalid", "details": "text is required"}, status=400)
        max_chars = int(settings.FLOBRAIN_V2.get("AI_MAX_INPUT_CHARS", 8000))
        if len(text) > max_chars:
            return Response({"error": "invalid", "details": f"text is longer than {max_chars} characters"}, status=400)
        # --- W5 hook (crew): Flo routes to other buddies; every reply's timing is measured. ---
        import time

        from buddies.router import flo_turn, is_flo, record_answer

        started = time.monotonic()
        if is_flo(chat.buddy):
            status, body = flo_turn(request.user, org, chat, text, request.data or {})
        else:
            status, body = run_buddy_turn(request.user, org, chat, text, request.data or {})
            if status == 200:
                record_answer(org, chat.buddy, chat, int((time.monotonic() - started) * 1000), body.get("citations"))
        # --- end W5 hook ---
        if status != 200:
            return Response(body, status=status)
        chat.save(update_fields=["updated_at"])
        return Response(_thread_payload(chat, body.get("usage"), {k: v for k, v in body.items() if k != "usage"}))



def _editable(request, org, buddy_id):
    """The buddy if this user may edit it; 404 when not visible; 403 when visible but not editable."""
    buddy = Buddy.objects.filter(org=org, pk=buddy_id).first()
    if buddy is None:
        return None, Response({"error": "not_found", "details": "Buddy not found"}, status=404)
    if can_edit(request.user, org, buddy):
        return buddy, None
    if visible_buddies(request.user, org).filter(pk=buddy.pk).exists():
        return None, Response({"error": "permission_denied", "details": "You cannot edit this buddy"}, status=403)
    return None, Response({"error": "not_found", "details": "Buddy not found"}, status=404)


class BuddyDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Read a buddy's builder settings (people who can only use it get the public card)")
    def get(self, request, org_id, buddy_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        buddy, error = _editable(request, org, buddy_id)
        if error is not None and error.status_code == 403:
            # W5: a buddy you can use but not edit (built-ins, Flo, shared buddies) still opens its chat page.
            usable = visible_buddies(request.user, org).filter(pk=buddy_id).first()
            if usable is not None and _flo_hidden(request, org, usable):
                return Response({"error": "not_found", "details": "Buddy not found"}, status=404)
            if usable is not None:
                return Response(buddy_payload(usable, None, request.user))
        if error:
            return error
        if _flo_hidden(request, org, buddy):
            return Response({"error": "not_found", "details": "Buddy not found"}, status=404)
        return Response(_full_payload(buddy, request.user))

    @extend_schema(summary="Edit a buddy; changing prompt, sources, tools or model re-opens approval")
    def patch(self, request, org_id, buddy_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        buddy, error = _editable(request, org, buddy_id)
        if error:
            return error
        data = request.data or {}
        try:
            fields = clean_definition(request.user, org, data, partial=True)
        except BuddyInvalid as exc:
            return _invalid(exc)
        if "is_enabled" in data:
            if not can(request.user, "buddy.manage", org) and buddy.is_builtin:
                return Response({"error": "permission_denied", "details": "buddy.manage is required"}, status=403)
            fields["is_enabled"] = bool(data.get("is_enabled"))
        for key, value in fields.items():
            setattr(buddy, key, value)
        # --- M5 hook (evals): sets with "block saves" must still pass with the new settings.
        from evals.gate import buddy_save_block

        blocked = buddy_save_block(request, org, buddy, fields)
        if blocked is not None:
            return blocked
        # --- end M5 hook
        reopened = False
        if (
            not buddy.is_builtin
            and buddy.share_status == Buddy.SHARE_APPROVED
            and buddy.visibility != Buddy.VIS_PRIVATE
            and REAPPROVAL_FIELDS & set(fields)
        ):
            # Viewers approved the old behaviour; the new one waits for the same approver.
            buddy.share_status = Buddy.SHARE_PENDING
            buddy.share_target = buddy.visibility
            buddy.share_team = buddy.team
            reopened = True
        buddy.save()
        audit(
            request.user,
            "buddy.update",
            target=buddy,
            payload={"fields": sorted(fields), "share_reopened": reopened},
            request=request,
            org=org,
        )
        return Response(_full_payload(buddy, request.user))

    @extend_schema(summary="Delete a buddy")
    def delete(self, request, org_id, buddy_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        buddy, error = _editable(request, org, buddy_id)
        if error:
            return error
        audit(request.user, "buddy.delete", target=buddy, request=request, org=org)
        buddy.delete()
        return Response(status=204)


def _person(user):
    return {"id": str(user.id), "name": user.username or user.email} if user else None


def _deciders(org, buddy):
    """Who can decide this pending share: ``buddy.manage`` holders, plus the team's leads for a team share."""
    from organizations.permissions import can as _can

    ids = []
    for membership in OrgMembership.objects.filter(org=org, employment_status=OrgMembership.STATUS_ACTIVE).select_related("user"):
        if _can(membership.user, "buddy.manage", org):
            ids.append(membership.user_id)
    if buddy.share_target == Buddy.VIS_TEAM and buddy.share_team_id:
        ids += list(
            TeamMembership.objects.filter(team_id=buddy.share_team_id, team_role=TeamMembership.ROLE_LEAD).values_list(
                "user_id", flat=True
            )
        )
    return set(ids)


def _notify_share_request(org, buddy, requester):
    from notifications.services import notify

    targets = _deciders(org, buddy) - {requester.id}
    where = buddy.share_team.name if buddy.share_target == Buddy.VIS_TEAM and buddy.share_team else "the organization"
    notify(
        org,
        targets,
        "buddy_share_request",
        {
            "text": f"{requester.username or requester.email} asked to share {buddy.name} with {where}",
            "buddy": str(buddy.id),
            "name": buddy.name,
            "by": requester.username or requester.email,
            "target": buddy.share_target,
            "team": where if buddy.share_target == Buddy.VIS_TEAM else "",
        },
        link="buddies/requests",
    )


def _notify_share_decided(org, buddy, decision, decider, reason=""):
    from notifications.services import notify

    if not buddy.created_by_id or buddy.created_by_id == decider.id:
        return
    approved = decision == "approve"
    notify(
        org,
        [buddy.created_by_id],
        "buddy_share_decided",
        {
            "text": f"Your request to share {buddy.name} was {'approved' if approved else 'rejected'}",
            "buddy": str(buddy.id),
            "name": buddy.name,
            "outcome": "approved" if approved else "rejected",
            "by": decider.username or decider.email,
            "reason": reason,
        },
        link=f"buddies/{buddy.id}",
    )


class BuddyShareView(V2APIView):
    """POST {"target": "team", "team": id} | {"target": "org"} | {"target": "private"}."""

    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Ask to share a buddy with a team or the org, or make it private again")
    def post(self, request, org_id, buddy_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        buddy, error = _editable(request, org, buddy_id)
        if error:
            return error
        if buddy.is_builtin:
            return Response({"error": "invalid", "details": "Built-in buddies are already shared"}, status=400)
        target = (request.data or {}).get("target")
        if target == Buddy.VIS_PRIVATE:
            buddy.visibility, buddy.team = Buddy.VIS_PRIVATE, None
            buddy.share_status, buddy.share_target, buddy.share_team = Buddy.SHARE_NONE, "", None
            buddy.save()
            audit(request.user, "buddy.unshare", target=buddy, request=request, org=org)
            return Response(_full_payload(buddy, request.user))
        team = None
        if target == Buddy.VIS_TEAM:
            team = Team.objects.filter(org=org, pk=(request.data or {}).get("team")).first()
            if team is None or not (
                TeamMembership.objects.filter(team=team, user=request.user).exists()
                or can(request.user, "buddy.manage", org)
            ):
                return Response({"error": "not_found", "details": "Team not found"}, status=404)
        elif target != Buddy.VIS_ORG:
            return _invalid("target must be team, org or private")
        buddy.share_status, buddy.share_target, buddy.share_team = Buddy.SHARE_PENDING, target, team
        approved = can_decide_share(request.user, org, buddy)
        if approved:
            # The requester is the approver (a lead sharing with their own team, or an admin).
            buddy.visibility, buddy.team = target, team
            buddy.share_status, buddy.share_decided_by = Buddy.SHARE_APPROVED, request.user
        buddy.save()
        audit(
            request.user,
            "buddy.share_request",
            target=buddy,
            payload={"target": target, "team": str(team.id) if team else None, "auto_approved": approved},
            request=request,
            org=org,
        )
        if not approved:
            _notify_share_request(org, buddy, request.user)
        return Response(_full_payload(buddy, request.user), status=200 if approved else 202)


class BuddyShareDecisionView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Approve or reject a buddy share request")
    def post(self, request, org_id, buddy_id, decision):
        if decision not in ("approve", "reject"):
            return Response({"error": "not_found", "details": "Unknown decision"}, status=404)
        org, error = _gate(request, self, org_id)
        if error:
            return error
        buddy = Buddy.objects.filter(org=org, pk=buddy_id, share_status=Buddy.SHARE_PENDING).first()
        if buddy is None:
            return Response({"error": "not_found", "details": "No pending share"}, status=404)
        if not can_decide_share(request.user, org, buddy):
            return Response({"error": "permission_denied", "details": "You cannot decide this share"}, status=403)
        reason = (request.data or {}).get("reason") if isinstance(request.data, dict) else ""
        if reason is not None and not isinstance(reason, str):
            return _invalid("reason must be text")
        reason = (reason or "").strip()[:300]
        if decision == "approve":
            if (request.data or {}).get("hash") != behaviour_hash(buddy):
                return Response(
                    {"error": "changed", "details": "The buddy changed since you reviewed it", "hash": behaviour_hash(buddy)},
                    status=409,
                )
            buddy.visibility, buddy.team = buddy.share_target, buddy.share_team
            buddy.share_status = Buddy.SHARE_APPROVED
        else:
            buddy.share_status = Buddy.SHARE_REJECTED
            buddy.visibility, buddy.team = Buddy.VIS_PRIVATE, None
        buddy.share_decided_by = request.user
        buddy.save()
        audit(
            request.user,
            f"buddy.share_{decision}",
            target=buddy,
            payload={"reason": reason} if reason else None,
            request=request,
            org=org,
        )
        _notify_share_decided(org, buddy, decision, request.user, reason)
        return Response(_full_payload(buddy, request.user) if can_edit(request.user, org, buddy) else buddy_payload(buddy))


class BuddyShareRequestListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Pending buddy share requests you can decide")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        from rooms.services import accessible_rooms

        rows = [
            b
            for b in Buddy.objects.filter(org=org, share_status=Buddy.SHARE_PENDING).select_related("share_team", "created_by")
            if can_decide_share(request.user, org, b)
        ]
        readable = {str(pk) for pk in accessible_rooms(request.user, org).values_list("pk", flat=True)}
        out = []
        for b in rows:
            data = _full_payload(b, request.user)
            sources = dict(data.get("allowed_sources") or {})
            if sources.get("rooms"):
                # Reviewers see the rooms they can read; the rest only as a count.
                rooms = [r for r in sources["rooms"] if r in readable]
                sources["hidden_rooms"] = len(sources["rooms"]) - len(rooms)
                sources["rooms"] = rooms
            data["allowed_sources"] = sources
            data["hash"] = behaviour_hash(b)
            data["requested_by"] = _person(b.created_by)
            data["share_team_name"] = b.share_team.name if b.share_team_id else None
            data["updated_at"] = b.updated_at.isoformat()
            out.append(data)
        return Response(out)
