import uuid

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, Throttled
from rest_framework.response import Response

from core_v2.pagination import V2CursorPagination
from core_v2.views import V2APIView
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization, Team
from organizations.permissions import HasPerm, IsActiveOrgMember, get_scoped_or_404, is_org_owner_or_admin
from organizations.services.members import can_receive_dm
from rooms.models import Announcement, Room, RoomMember, RoomMessage
from rooms.serializers import (
    AnnouncementCreateSerializer,
    RoomCreateSerializer,
    RoomMessageSerializer,
    RoomPatchSerializer,
    TranslateQuerySerializer,
)
from organizations.services.core import audit
from rooms.services import (
    accessible_rooms,
    display_name,
    ensure_team_room,
    notify_new_message,
    pair_key_for,
    post_message,
    user_can_access_room,
)
from rooms.translation import translate_page
from users.models import User


def _org(org_id):
    return get_object_or_404(Organization, pk=org_id, is_active=True)


def _room_or_404(user, org, room_id):
    room = get_object_or_404(Room, pk=room_id, org=org)
    if not user_can_access_room(user, room):
        raise NotFound()
    get_scoped_or_404(user, "room.view", room)
    return room


def _unread_count(room, user):
    membership = RoomMember.objects.filter(room=room, user=user).first()
    qs = RoomMessage.objects.filter(room=room, deleted_at__isnull=True)
    if membership and membership.last_read_at:
        qs = qs.filter(created_at__gt=membership.last_read_at)
    return qs.count()


def _dm_others(rooms, user) -> dict:
    """The other person of each direct room, in one query (room lists)."""
    ids = [r.id for r in rooms if r.kind == Room.KIND_DIRECT]
    if not ids:
        return {}
    return {m.room_id: m for m in RoomMember.objects.filter(room_id__in=ids).exclude(user=user).select_related("user")}


def _room_payload(room, user=None, others=None):
    data = {
        "id": str(room.id),
        "name": room.name,
        "kind": room.kind,
        "team": str(room.team_id) if room.team_id else None,
    }
    if user is not None:
        data["unread"] = _unread_count(room, user)
        if room.kind == Room.KIND_DIRECT:
            other = others.get(room.id) if others is not None else RoomMember.objects.filter(room=room).exclude(user=user).select_related("user").first()
            if other is not None:
                data["other_user"] = str(other.user_id)
                data["other_name"] = display_name(other.user)
    return data


def _message_payload(message, translation=None):
    """``translation`` is (text, error_code) from ``translate_page``, or None when not asked."""
    data = {
        "id": str(message.id),
        "body": message.body,
        "author": str(message.author_id) if message.author_id else None,
        "author_name": display_name(message.author),
        "author_avatar": (message.author.avatar_url or None) if message.author else None,
        "created_at": message.created_at.isoformat(),
        "edited_at": message.edited_at.isoformat() if message.edited_at else None,
        "translated": False,
    }
    if translation is not None:
        text, error = translation
        if text is not None and not error:
            data["translation"] = text
            data["translated"] = True
        else:
            data["translation_error"] = error or "provider_error"
    return data


class RoomListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("room.view").has_permission(request, self)
        qs = accessible_rooms(request.user, org).filter(is_active=True).order_by("name")
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(name__icontains=q)
        rooms = list(qs)
        others = _dm_others(rooms, request.user)
        return Response([_room_payload(room, request.user, others) for room in rooms])

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        serializer = RoomCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data.get("user_id"):
            HasPerm("chat.use").has_permission(request, self)
            other = get_object_or_404(User, pk=data["user_id"])
            if other.id == request.user.id:
                return Response({"error": "invalid", "details": "You can't start a direct message with yourself"}, status=400)
            if not can_receive_dm(other, org):
                return Response({"error": "not_found", "details": "Recipient not found"}, status=404)
            key = pair_key_for(request.user, other)
            room, _ = Room.objects.get_or_create(
                org=org,
                kind=Room.KIND_DIRECT,
                pair_key=key,
                defaults={"name": f"{request.user.username or request.user.email} / {other.username or other.email}"},
            )
            RoomMember.objects.get_or_create(room=room, user=request.user)
            RoomMember.objects.get_or_create(room=room, user=other)
            return Response(_room_payload(room, request.user), status=201)
        if data.get("team"):
            team = get_object_or_404(Team, pk=data["team"], org=org)
            get_scoped_or_404(request.user, "room.manage", team)
            return Response(_room_payload(ensure_team_room(team)), status=201)
        HasPerm("room.manage").has_permission(request, self)
        invited = []
        for user_id in dict.fromkeys(data.get("user_ids") or []):
            person = User.objects.filter(pk=user_id).first()
            if person is None or not can_receive_dm(person, org):
                return Response({"error": "invalid", "details": "Every person must be an active member"}, status=400)
            if person.id != request.user.id:
                invited.append(person)
        name = (data.get("name") or "").strip() or "Room"
        room = Room.objects.create(org=org, name=name[:200], kind=Room.KIND_GROUP)
        RoomMember.objects.get_or_create(room=room, user=request.user)
        for person in invited:
            RoomMember.objects.get_or_create(room=room, user=person)
        audit(request.user, "room.create", target=room, org=org, request=request, payload={"members": len(invited) + 1})
        return Response(_room_payload(room, request.user), status=201)


class RoomDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, room_id):
        org = _org(org_id)
        request.org = org
        room = _room_or_404(request.user, org, room_id)
        return Response(_room_payload(room, request.user))

    def patch(self, request, org_id, room_id):
        org = _org(org_id)
        request.org = org
        HasPerm("room.manage").has_permission(request, self)
        room = _room_or_404(request.user, org, room_id)
        serializer = RoomPatchSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if "name" in serializer.validated_data:
            room.name = serializer.validated_data["name"]
            room.save(update_fields=["name", "updated_at"])
        return Response(_room_payload(room))


class RoomMemberListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, room_id):
        org = _org(org_id)
        request.org = org
        room = _room_or_404(request.user, org, room_id)
        rows = list(RoomMember.objects.filter(room=room).select_related("user"))
        memberships = {
            m.user_id: m for m in OrgMembership.objects.filter(org=org, user_id__in=[row.user_id for row in rows])
        }
        out = []
        for row in rows:
            membership = memberships.get(row.user_id)
            active = bool(membership and membership.is_active_member)
            out.append(
                {
                    "user_id": str(row.user_id),
                    "username": row.user.username,
                    "name": display_name(row.user),
                    "avatar_url": row.user.avatar_url or None,
                    "presence": (membership.presence if membership and active else "offline"),
                    "active": active,
                }
            )
        out.sort(key=lambda r: (not r["active"], r["presence"] == "offline", r["name"].lower()))
        return Response(out)


class RoomMessageListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, room_id):
        org = _org(org_id)
        request.org = org
        HasPerm("chat.use").has_permission(request, self)
        room = _room_or_404(request.user, org, room_id)
        from console.impersonation import is_impersonated

        support = is_impersonated(request)
        if not support:  # a support session must not change what the person has read
            RoomMember.objects.filter(room=room, user=request.user).update(last_read_at=timezone.now())
        qs = RoomMessage.objects.filter(room=room, deleted_at__isnull=True).select_related("author")
        paginator = V2CursorPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        query = TranslateQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        lang = query.validated_data.get("translate_to") or ""
        if not lang:
            return paginator.get_paginated_response([_message_payload(m) for m in page])
        if support:  # translation spends money and sends room text to a model
            return Response({"error": "permission_denied", "details": "impersonation_read_only"}, status=403)
        membership = OrgMembership.objects.filter(org=org, user=request.user).first()
        if not effective_flag(org, membership, "live_translation", default=False):
            return Response(
                {"error": "not_implemented", "details": "Live translation is not implemented"},
                status=501,
            )
        from brain.llm import direct

        if not direct.is_configured():
            return Response(
                {"error": "not_configured", "details": "No direct AI provider is configured"},
                status=501,
            )
        from brain.llm.policy import check_ai

        if check_ai(org, "direct"):
            return Response({"error": "private_only", "details": "This organization only allows self-hosted models"}, status=409)
        from brain.throttles import AISendThrottle

        throttle = AISendThrottle()
        if not throttle.allow_request(request, self):
            raise Throttled(wait=throttle.wait())
        translations = translate_page(list(page), lang, request.user, org)
        return paginator.get_paginated_response(
            [_message_payload(m, translations.get(m.id)) for m in page]
        )

    def post(self, request, org_id, room_id):
        org = _org(org_id)
        request.org = org
        HasPerm("chat.use").has_permission(request, self)
        room = _room_or_404(request.user, org, room_id)
        serializer = RoomMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message, reason = post_message(room, request.user, serializer.validated_data["body"])
        if reason == "empty":
            return Response({"error": "invalid", "details": "body is required"}, status=400)
        if reason == "too_long":
            return Response({"error": "invalid", "details": "body is too long"}, status=400)
        if reason:
            return Response({"error": "permission_denied", "details": "Cannot post"}, status=403)
        notify_new_message(room, message, request.user)
        return Response(_message_payload(message), status=201)


class RoomMessageDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def patch(self, request, org_id, room_id, message_id):
        org = _org(org_id)
        request.org = org
        HasPerm("chat.use").has_permission(request, self)
        room = _room_or_404(request.user, org, room_id)
        message = get_object_or_404(RoomMessage, pk=message_id, room=room, deleted_at__isnull=True)
        if message.author_id != request.user.id:
            raise PermissionDenied("Cannot edit this message")
        serializer = RoomMessageSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if "body" not in serializer.validated_data:
            return Response({"error": "invalid", "details": "body is required"}, status=400)
        if serializer.validated_data["body"] != message.body:
            message.body = serializer.validated_data["body"]
            message.edited_at = timezone.now()
            message.save(update_fields=["body", "edited_at", "updated_at"])
            # Ids only: the text of a message never goes into the audit log.
            audit(request.user, "room.message.edit", target=message, org=org, request=request, payload={"room": str(room.id)})
        return Response(_message_payload(message))

    def delete(self, request, org_id, room_id, message_id):
        org = _org(org_id)
        request.org = org
        HasPerm("chat.use").has_permission(request, self)
        room = _room_or_404(request.user, org, room_id)
        message = get_object_or_404(RoomMessage, pk=message_id, room=room, deleted_at__isnull=True)
        if message.author_id != request.user.id:
            raise PermissionDenied("Cannot delete this message")
        message.deleted_at = timezone.now()
        message.save(update_fields=["deleted_at"])
        audit(request.user, "room.message.delete", target=message, org=org, request=request, payload={"room": str(room.id)})
        return Response(status=204)


class RoomSearchView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("room.view").has_permission(request, self)
        q = (request.query_params.get("q") or "").strip()
        qs = accessible_rooms(request.user, org).filter(is_active=True)
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(messages__body__icontains=q))
        rooms = list(qs.distinct()[:50])
        others = _dm_others(rooms, request.user)
        return Response([_room_payload(room, request.user, others) for room in rooms])


def _announcement_payload(row):
    return {
        "id": str(row.id),
        "body": row.body,
        "room": str(row.room_id),
        "room_name": row.room.name,
        "pinned": row.pinned,
        "author_name": display_name(row.created_by) if row.created_by_id else None,
        "created_at": row.created_at.isoformat(),
    }


class AnnouncementListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        """Pinned announcements in rooms you can read. ``?room=`` narrows to one room;
        ``?include_unpinned=1`` also lists unpinned ones (``announcement.manage`` only)."""
        org = _org(org_id)
        request.org = org
        HasPerm("room.view").has_permission(request, self)
        rooms = accessible_rooms(request.user, org)
        rows = Announcement.objects.filter(org=org, room__in=rooms).select_related("room", "created_by")
        room_id = (request.query_params.get("room") or "").strip()
        if room_id:
            try:
                rows = rows.filter(room_id=uuid.UUID(room_id))
            except ValueError:
                return Response({"error": "invalid", "details": "room must be a room id"}, status=400)
        if request.query_params.get("include_unpinned") in {"1", "true"}:
            HasPerm("announcement.manage").has_permission(request, self)
        else:
            rows = rows.filter(pinned=True)
        return Response([_announcement_payload(row) for row in rows.order_by("-created_at")[:100]])

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("announcement.manage").has_permission(request, self)
        serializer = AnnouncementCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        room = _room_or_404(request.user, org, serializer.validated_data["room"])
        row = Announcement.objects.create(
            org=org, room=room, body=serializer.validated_data["body"], created_by=request.user
        )
        audit(request.user, "announcement.create", target=row, org=org, request=request, payload={"room": str(room.id)})
        from notifications.services import notify

        others = RoomMember.objects.filter(room=room).exclude(user=request.user).values_list("user_id", flat=True)
        by = display_name(request.user)
        notify(
            org,
            list(others),
            "announcement",
            {"room": str(room.id), "by": by, "room_name": room.name, "text": f"New announcement in {room.name}"},
            link=f"rooms/{room.id}",
        )
        return Response(_announcement_payload(row), status=201)


def _set_pinned(view, request, org_id, announcement_id, pinned: bool):
    org = _org(org_id)
    request.org = org
    HasPerm("announcement.manage").has_permission(request, view)
    row = get_object_or_404(Announcement.objects.select_related("room", "created_by"), pk=announcement_id, org=org)
    if not user_can_access_room(request.user, row.room):
        raise NotFound()
    if row.pinned != pinned:
        row.pinned = pinned
        row.save(update_fields=["pinned"])
        audit(request.user, "announcement.pin" if pinned else "announcement.unpin", target=row, org=org, request=request)
    return Response(_announcement_payload(row))


class AnnouncementUnpinView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, announcement_id):
        return _set_pinned(self, request, org_id, announcement_id, False)


class AnnouncementPinView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, announcement_id):
        return _set_pinned(self, request, org_id, announcement_id, True)
