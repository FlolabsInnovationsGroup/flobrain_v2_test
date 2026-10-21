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
    for membership in TeamMembership.objects.filter(team=team):
        RoomMember.objects.get_or_create(room=room, user=membership.user)
    return room


def ensure_project_room(project):
    room, _ = Room.objects.get_or_create(
        org=project.org,
        project=project,
        kind=Room.KIND_PROJECT,
        defaults={"name": project.name},
    )
    user_ids = set(ProjectMembership.objects.filter(project=project).values_list("user_id", flat=True))
    for team in project.teams.all():
        user_ids.update(TeamMembership.objects.filter(team=team).values_list("user_id", flat=True))
    if project.lead_id:
        user_ids.add(project.lead_id)
    for user_id in user_ids:
        RoomMember.objects.get_or_create(room=room, user_id=user_id)
    return room


def user_can_access_room(user, room) -> bool:
    from organizations.permissions.engine import is_org_owner_or_admin

    if is_org_owner_or_admin(user, room.org):
        return True
    return RoomMember.objects.filter(room=room, user=user).exists()


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
