"""Flo routing hints, specialist templates, buddy feedback and the quality page (growth round W5).

All of these need the ``buddies`` flag (501, like the rest of the buddies API) and ``flo_router``
(501 when off). Checks after that:

- ``POST /orgs/{org}/buddies/route`` (``ai.use``): the routing decision only, for UI hints.
- ``GET /orgs/{org}/buddies/templates`` (``ai.use``); ``POST .../templates/{key}/install`` (``buddy.manage``).
- ``GET|POST /orgs/{org}/buddies/feedback`` and ``DELETE .../feedback/{message}`` (``ai.use``): your own
  thumbs on replies in your own buddy threads.
- ``GET /orgs/{org}/buddies/quality?days=7|30`` (``pulse.view`` or ``ai.usage.view``): numbers only.
"""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from brain.models import Chat, Message
from brain.throttles import AISendThrottle
from buddies import quality, router
from buddies.models import Buddy, BuddyFeedback, BuddyRoute
from buddies.services import visible_buddies
from buddies.templates_extra import TEMPLATES, ensure_flo, install
from core_v2.throttles import V2UserThrottle
from core_v2.views import V2APIView
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization
from organizations.permissions import HasPerm, IsActiveOrgMember, can
from organizations.services.core import audit


def _off(details):
    return Response({"error": "not_implemented", "details": details}, status=501)


def _gate(request, view, org_id, perm="ai.use"):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    if perm:
        HasPerm(perm).has_permission(request, view)
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, "buddies", default=False):
        return org, _off("Buddies are not enabled")
    if not effective_flag(org, membership, router.FLAG, default=False):
        return org, _off("Flo and buddy quality are not enabled")
    return org, None


def _invalid(details):
    return Response({"error": "invalid", "details": details}, status=400)


class BuddyRouteView(V2APIView):
    permission_classes = [IsActiveOrgMember]
    throttle_classes = [V2UserThrottle, AISendThrottle]

    @extend_schema(summary="Which buddy Flo would ask (decision only, nothing is answered)")
    def post(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        data = request.data if isinstance(request.data, dict) else {}
        text = data.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            return _invalid("text is required (at most 4000 characters)")
        room = None
        if data.get("room"):
            from rooms.services import accessible_rooms

            room = accessible_rooms(request.user, org).filter(pk=str(data.get("room"))).first() if _is_uuid(data.get("room")) else None
            if room is None:
                return Response({"error": "not_found", "details": "Room not found"}, status=404)
        decision = router.decide(request.user, org, text.strip(), room=room)
        router.log(org, request.user, decision, BuddyRoute.SURFACE_HINT, hops=[(b, None, 0) for b in decision.buddies])
        return Response(router.decision_payload(decision))


def _is_uuid(value):
    import uuid

    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


def _template_payload(key, spec, installed):
    buddy = installed.get(spec["slug"])
    return {
        "key": key,
        "slug": spec["slug"],
        "name": spec["name"],
        "description": spec["description"],
        "icon": spec["icon"],
        "gradient": spec["gradient"],
        "starter_prompts": [p["prompt"] for p in spec.get("preset_prompts", [])],
        "tools": spec.get("allowed_tools", []),
        "channel_only": bool(spec.get("channel_only")),
        "installed": bool(buddy and buddy.is_enabled),
        "buddy": str(buddy.id) if buddy else None,
    }


class BuddyTemplateListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Specialist buddy templates and whether this org has them")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        slugs = [spec["slug"] for spec in TEMPLATES.values()]
        installed = {b.slug: b for b in Buddy.objects.filter(org=org, slug__in=slugs, is_builtin=True)}
        flo = Buddy.objects.filter(org=org, slug=router.FLO_SLUG, is_builtin=True).first() or ensure_flo(org)
        return Response(
            {
                "flo": {"id": str(flo.id), "name": flo.name, "enabled": flo.is_enabled},
                "can_install": can(request.user, "buddy.manage", org),
                "templates": [_template_payload(key, spec, installed) for key, spec in TEMPLATES.items()],
            }
        )


class BuddyTemplateInstallView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Install a specialist buddy for the whole org (buddy.manage)")
    def post(self, request, org_id, key):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        if key not in TEMPLATES:
            return Response({"error": "not_found", "details": "Unknown template"}, status=404)
        HasPerm("buddy.manage").has_permission(request, self)
        buddy, created = install(org, key)
        audit(request.user, "buddy.template_install", target=buddy, payload={"template": key, "created": created}, request=request, org=org)
        installed = {buddy.slug: buddy}
        return Response(_template_payload(key, TEMPLATES[key], installed), status=201 if created else 200)


def _rated_message(request, org, message_id):
    """An assistant reply in one of your own buddy threads, on a buddy you can still use."""
    message = (
        Message.objects.filter(
            pk=message_id, role=Message.ROLE_ASSISTANT, chat__org=org, chat__user=request.user, chat__buddy__isnull=False
        )
        .select_related("chat__buddy")
        .first()
    )
    if message is None or not visible_buddies(request.user, org).filter(pk=message.chat.buddy_id).exists():
        return None
    return message


def _feedback_payload(fb):
    return {
        "message": fb.message_id,
        "buddy": str(fb.buddy_id),
        "rating": "up" if fb.rating == BuddyFeedback.UP else "down",
        "reason": fb.reason,
        "note": fb.note,
    }


RATINGS = {"up": BuddyFeedback.UP, "down": BuddyFeedback.DOWN, 1: BuddyFeedback.UP, -1: BuddyFeedback.DOWN}


class BuddyFeedbackView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Your thumbs on replies in one of your buddy threads (?thread=id)")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        thread = request.query_params.get("thread", "")
        if not thread.isdigit():
            return _invalid("thread is required")
        chat = Chat.objects.filter(pk=int(thread), org=org, user=request.user, buddy__isnull=False).first()
        if chat is None:
            return Response({"error": "not_found", "details": "Thread not found"}, status=404)
        rows = BuddyFeedback.objects.filter(user=request.user, message__chat=chat)
        return Response([_feedback_payload(fb) for fb in rows])

    @extend_schema(summary="Rate a buddy reply: helpful or not, with an optional reason (one per person per reply)")
    def post(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        data = request.data if isinstance(request.data, dict) else {}
        message_id = data.get("message")
        if isinstance(message_id, bool) or not str(message_id or "").isdigit():
            return _invalid("message must be a reply id")
        rating = RATINGS.get(data.get("rating"))
        if rating is None:
            return _invalid("rating must be up or down")
        reason = data.get("reason") or ""
        if not isinstance(reason, str) or (reason and reason not in BuddyFeedback.REASONS):
            return _invalid(f"reason must be one of {', '.join(BuddyFeedback.REASONS)}")
        note = data.get("note") or ""
        if not isinstance(note, str) or len(note) > 300:
            return _invalid("note must be text of at most 300 characters")
        if rating == BuddyFeedback.UP:
            reason = ""
        message = _rated_message(request, org, int(message_id))
        if message is None:
            return Response({"error": "not_found", "details": "Reply not found"}, status=404)
        buddy = message.chat.buddy
        if router.is_flo(buddy):
            # A Flo reply is rated for the buddy that answered it (the caller may name one of them).
            hops = router.answered_by(message.chat).get(str(message.id), [])
            names = {h["id"] for h in hops}
            wanted = data.get("buddy")
            if wanted and str(wanted) not in names:
                return _invalid("buddy must be one of the buddies that answered")
            target = str(wanted) if wanted else (hops[0]["id"] if hops else None)
            if target:
                buddy = Buddy.objects.filter(org=org, pk=target).first() or buddy
        fb, created = BuddyFeedback.objects.update_or_create(
            user=request.user,
            message=message,
            defaults={"org": org, "buddy": buddy, "rating": rating, "reason": reason, "note": note.strip()},
        )
        return Response(_feedback_payload(fb), status=201 if created else 200)


class BuddyFeedbackDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Remove your rating of one reply")
    def delete(self, request, org_id, message_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        deleted, _ = BuddyFeedback.objects.filter(org=org, user=request.user, message_id=message_id).delete()
        if not deleted:
            return Response({"error": "not_found", "details": "No rating"}, status=404)
        return Response(status=204)


class BuddyQualityView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Buddy quality for 7 or 30 days (numbers only, no message text)")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id, perm=None)
        if error:
            return error
        if not (can(request.user, "pulse.view", org) or can(request.user, "ai.usage.view", org)):
            return Response({"error": "permission_denied", "details": "Missing permission: pulse.view or ai.usage.view"}, status=403)
        raw = request.query_params.get("days", "7")
        if not raw.isdigit() or int(raw) not in quality.WINDOWS:
            return _invalid("days must be 7 or 30")
        return Response(quality.stats(org, request.user, int(raw)))
