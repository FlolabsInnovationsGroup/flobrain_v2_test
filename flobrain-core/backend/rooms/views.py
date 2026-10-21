from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from core_v2.pagination import V2CursorPagination
from core_v2.views import V2APIView
from organizations.models import Organization, Team
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
from rooms.services import ensure_team_room, pair_key_for, post_message, user_can_access_room
from rooms.translation import translated_text
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


def _room_payload(room, user=None):
    data = {
        "id": str(room.id),
        "name": room.name,
        "kind": room.kind,
        "team": str(room.team_id) if room.team_id else None,
    }
    if user is not None:
        data["unread"] = _unread_count(room, user)
    return data


def _message_payload(message, translate_to=""):
    data = {
        "id": str(message.id),
        "body": message.body,
        "author": str(message.author_id) if message.author_id else None,
        "created_at": message.created_at.isoformat(),
        "translated": False,
    }
    if translate_to:
        data["translation"] = translated_text(message, translate_to)
        data["translated"] = True
    return data


class RoomListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("room.view").has_permission(request, self)
        qs = Room.objects.filter(org=org, is_active=True)
        if not is_org_owner_or_admin(request.user, org):
            qs = qs.filter(memberships__user=request.user)
        qs = qs.distinct().order_by("name")
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(name__icontains=q)
        return Response([_room_payload(room, request.user) for room in qs])

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        serializer = RoomCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data.get("user_id"):
            HasPerm("chat.use").has_permission(request, self)
            other = get_object_or_404(User, pk=data["user_id"])
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
            return Response(_room_payload(room), status=201)
        if data.get("team"):
            team = get_object_or_404(Team, pk=data["team"], org=org)
            get_scoped_or_404(request.user, "room.manage", team)
            return Response(_room_payload(ensure_team_room(team)), status=201)
        HasPerm("room.manage").has_permission(request, self)
        room = Room.objects.create(org=org, name=(data.get("name") or "Room")[:200], kind=Room.KIND_GROUP)
        RoomMember.objects.get_or_create(room=room, user=request.user)
        return Response(_room_payload(room), status=201)


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
        rows = RoomMember.objects.filter(room=room).select_related("user")
        return Response([{"user_id": str(row.user_id), "username": row.user.username} for row in rows])


class RoomMessageListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, room_id):
        org = _org(org_id)
        request.org = org
        HasPerm("chat.use").has_permission(request, self)
        room = _room_or_404(request.user, org, room_id)
        RoomMember.objects.filter(room=room, user=request.user).update(last_read_at=timezone.now())
        qs = RoomMessage.objects.filter(room=room, deleted_at__isnull=True)
        paginator = V2CursorPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        query = TranslateQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        lang = query.validated_data.get("translate_to") or ""
        if lang:
            return Response(
                {"error": "not_implemented", "details": "Live translation is not implemented"},
                status=501,
            )
        return paginator.get_paginated_response([_message_payload(m, lang) for m in page])

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
        from notifications.models import Notification

        for member in RoomMember.objects.filter(room=room).exclude(user=request.user):
            Notification.objects.create(
                org=org,
                user=member.user,
                kind="room_message",
                payload={"room": str(room.id), "message": str(message.id)},
            )
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
        if "body" in serializer.validated_data:
            message.body = serializer.validated_data["body"]
            message.save(update_fields=["body", "updated_at"])
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
        return Response(status=204)


class RoomSearchView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("room.view").has_permission(request, self)
        q = (request.query_params.get("q") or "").strip()
        qs = Room.objects.filter(org=org, is_active=True)
        if not is_org_owner_or_admin(request.user, org):
            qs = qs.filter(memberships__user=request.user)
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(messages__body__icontains=q))
        return Response([_room_payload(room, request.user) for room in qs.distinct()[:50]])


class AnnouncementListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("room.view").has_permission(request, self)
        rooms = Room.objects.filter(org=org, memberships__user=request.user)
        rows = Announcement.objects.filter(org=org, room__in=rooms, pinned=True).order_by("-created_at")
        return Response(
            [{"id": str(row.id), "body": row.body, "room": str(row.room_id), "pinned": row.pinned} for row in rows]
        )

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
        return Response({"id": str(row.id), "body": row.body, "pinned": row.pinned}, status=201)


class AnnouncementUnpinView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id, announcement_id):
        org = _org(org_id)
        request.org = org
        HasPerm("announcement.manage").has_permission(request, self)
        row = get_object_or_404(Announcement, pk=announcement_id, org=org)
        if not user_can_access_room(request.user, row.room):
            raise NotFound()
        row.pinned = False
        row.save(update_fields=["pinned"])
        return Response({"id": str(row.id), "pinned": False})
