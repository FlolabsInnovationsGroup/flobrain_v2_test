import re

from django.conf import settings

from organizations.models import ProjectMembership, TeamMembership
from rooms.models import Room, RoomMember, RoomMessage


def pair_key_for(user_a, user_b) -> str:
    return ":".join(sorted([str(user_a.id), str(user_b.id)]))


def ensure_team_room(team):
    room, _ = Room.objects.get_or_create(
        org=team.org,
        team=team,
        kind=Room.KIND_TEAM,
        defaults={"name": team.name},
    )
    user_ids = set(TeamMembership.objects.filter(team=team).values_list("user_id", flat=True))
    for user_id in user_ids:
        RoomMember.objects.get_or_create(room=room, user_id=user_id)
    # Team room membership mirrors team membership: someone who left the team leaves the room.
    RoomMember.objects.filter(room=room).exclude(user_id__in=user_ids).delete()
    return room


def _project_member_ids(project) -> set:
    user_ids = set(ProjectMembership.objects.filter(project=project).values_list("user_id", flat=True))
    for team in project.teams.all():
        user_ids.update(TeamMembership.objects.filter(team=team).values_list("user_id", flat=True))
    if project.lead_id:
        user_ids.add(project.lead_id)
    return user_ids


def prune_project_room(project) -> None:
    """Remove room members who no longer belong to the project. Never creates rows."""
    room = Room.objects.filter(project=project, kind=Room.KIND_PROJECT).first()
    if room is not None:
        RoomMember.objects.filter(room=room).exclude(user_id__in=_project_member_ids(project)).delete()


def ensure_project_room(project):
    room, _ = Room.objects.get_or_create(
        org=project.org,
        project=project,
        kind=Room.KIND_PROJECT,
        defaults={"name": project.name},
    )
    user_ids = _project_member_ids(project)
    for user_id in user_ids:
        RoomMember.objects.get_or_create(room=room, user_id=user_id)
    # Project room membership mirrors project membership (direct, via teams, or as lead).
    RoomMember.objects.filter(room=room).exclude(user_id__in=user_ids).delete()
    return room


PRIVATE_ROOM_KINDS = (Room.KIND_DIRECT, Room.KIND_GROUP)


def _live_member_q(user):
    """RoomMember rows are a cache. For team and project rooms the live team/project
    membership decides, so a stale row (missed signal, race) never grants access."""
    from django.db.models import Q

    team_ids = TeamMembership.objects.filter(user=user).values("team_id")
    project_ids = ProjectMembership.objects.filter(user=user).values("project_id")
    from organizations.models import Project

    via_team = Project.teams.through.objects.filter(team_id__in=team_ids).values("project_id")
    led = Project.objects.filter(lead=user).values("pk")
    return (
        Q(kind__in=PRIVATE_ROOM_KINDS)
        | Q(kind=Room.KIND_TEAM, team_id__in=team_ids)
        | Q(kind=Room.KIND_PROJECT, project_id__in=project_ids)
        | Q(kind=Room.KIND_PROJECT, project_id__in=via_team)
        | Q(kind=Room.KIND_PROJECT, project_id__in=led)
    )


def accessible_rooms(user, org):
    """Rooms this user can read now: their rooms, plus team/project rooms for owners and admins."""
    from django.db.models import Q

    from organizations.permissions.engine import is_org_owner_or_admin

    qs = Room.objects.filter(org=org)
    member_ids = RoomMember.objects.filter(user=user, room__org=org).values("room_id")
    member = Q(pk__in=member_ids) & _live_member_q(user)
    if is_org_owner_or_admin(user, org):
        return Room.objects.filter(pk__in=qs.filter(member | ~Q(kind__in=PRIVATE_ROOM_KINDS)).values("pk"))
    return Room.objects.filter(pk__in=qs.filter(member).values("pk"))


def user_can_access_room(user, room) -> bool:
    """Members always; owners/admins for team and project rooms only.

    Direct and group rooms are private conversations: nobody outside the room
    (owners and admins included) can read them (Decision E37).
    """
    from organizations.permissions.engine import is_org_owner_or_admin

    if room.kind not in PRIVATE_ROOM_KINDS and is_org_owner_or_admin(user, room.org):
        return True
    if not RoomMember.objects.filter(room=room, user=user).exists():
        return False
    return Room.objects.filter(pk=room.pk).filter(_live_member_q(user)).exists()


def post_message(room, author, body: str):
    text = (body or "").strip()
    if not text:
        return None, "empty"
    max_len = getattr(settings, "FLOBRAIN_V2", {}).get("ROOM_MESSAGE_MAX_LENGTH", 8000)
    if len(text) > max_len:
        return None, "too_long"
    if not user_can_access_room(author, room):
        return None, "forbidden"
    message = RoomMessage.objects.create(room=room, author=author, body=text)
    return message, None


def display_name(user) -> str:
    """A person's name for chat. Never their email (contact details need their own permission)."""
    if user is None:
        return "Former member"
    return (user.username or "").strip() or "Member"


MENTION_START = re.compile(r"(?<![\w@])@")


def mentioned_users(room, text: str, exclude=None) -> list:
    """Room members named with ``@Full Name`` or ``@FirstName`` (first name only when unique in the room).

    Only people who can read the room are returned: a mention never reaches anyone outside it.
    """
    body = text or ""
    if "@" not in body:
        return []
    starts = [m.end() for m in MENTION_START.finditer(body)]
    if not starts:
        return []
    members = [
        row.user
        for row in RoomMember.objects.filter(room=room).select_related("user")
        if exclude is None or row.user_id != getattr(exclude, "id", exclude)
    ]
    firsts = {}
    for user in members:
        name = (user.username or "").strip()
        if name:
            first = name.split()[0].lower()
            firsts[first] = firsts.get(first, 0) + 1
    found = []
    lowered = body.lower()

    def _at(start, word):
        end = start + len(word)
        return lowered.startswith(word, start) and (end == len(lowered) or not (lowered[end].isalnum() or lowered[end] == "_"))

    for user in members:
        name = (user.username or "").strip().lower()
        if not name:
            continue
        first = name.split()[0]
        if any(_at(start, name) or (firsts.get(first) == 1 and _at(start, first)) for start in starts):
            if user_can_access_room(user, room):
                found.append(user)
    return found


def notify_new_message(room, message, author) -> None:
    """In-app notifications for a new room message.

    - ``mention``: anyone named with ``@`` (any room kind).
    - ``direct_message``: every other member of a direct or group room.
    - Team and project rooms get no row per message; their unread count comes from read markers.

    Web Push for direct and group rooms stays in ``rooms.signals`` (title only, no text). A mention
    in a team or project room also pushes a title-only "X mentioned you".
    """
    from notifications.services import notify

    org = room.org
    by = display_name(author)
    link = f"rooms/{room.id}"
    base = {"room": str(room.id), "message": str(message.id), "by": by, "room_name": room.name}
    mentioned = mentioned_users(room, message.body, exclude=author)
    private = room.kind in PRIVATE_ROOM_KINDS
    if mentioned:
        notify(
            org,
            mentioned,
            "mention",
            {**base, "text": f"{by} mentioned you"},
            link=link,
            push=not private,
            push_title=f"{by} mentioned you",
        )
    if private:
        skip = {u.id for u in mentioned}
        others = [
            row.user_id
            for row in RoomMember.objects.filter(room=room).exclude(user_id=getattr(author, "id", None))
            if row.user_id not in skip
        ]
        notify(org, others, "direct_message", {**base, "text": f"New message from {by}"}, link=link)
