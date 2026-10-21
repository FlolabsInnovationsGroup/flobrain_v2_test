from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError

from organizations.models import OrgMembership, Organization, Project, Team, TeamMembership
from organizations.services import sync_user_type
from rooms.services import ensure_project_room, ensure_team_room
from users.models import User


class Command(BaseCommand):
    help = "Seed FloLabs org, three teams, leads and members. Refuses to run when DEBUG=False."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_v2_demo refuses to run when DEBUG=False")

        org, _ = Organization.objects.get_or_create(
            slug="flolabs",
            defaults={"name": "FloLabs"},
        )
        owner, _ = User.objects.get_or_create(
            email="owner@flolabs.local",
            defaults={
                "username": "FloLabs Owner",
                "password_hash": make_password("demo-owner-pass"),
            },
        )
        OrgMembership.objects.update_or_create(
            org=org,
            user=owner,
            defaults={
                "org_role": OrgMembership.ORG_ROLE_OWNER,
                "employment_status": OrgMembership.STATUS_ACTIVE,
            },
        )
        team_specs = (
            ("Product", "lead.product@flolabs.local", "member.product@flolabs.local"),
            ("Engineering", "lead.eng@flolabs.local", "member.eng@flolabs.local"),
            ("People", "lead.people@flolabs.local", "member.people@flolabs.local"),
        )
        for team_name, lead_email, member_email in team_specs:
            team, _ = Team.objects.get_or_create(org=org, name=team_name)
            lead, _ = User.objects.get_or_create(
                email=lead_email,
                defaults={
                    "username": team_name + " Lead",
                    "password_hash": make_password("demo-lead-pass"),
                },
            )
            member, _ = User.objects.get_or_create(
                email=member_email,
                defaults={
                    "username": team_name + " Member",
                    "password_hash": make_password("demo-member-pass"),
                },
            )
            for user, role in ((lead, OrgMembership.ORG_ROLE_MEMBER), (member, OrgMembership.ORG_ROLE_MEMBER)):
                OrgMembership.objects.update_or_create(
                    org=org,
                    user=user,
                    defaults={
                        "org_role": role,
                        "employment_status": OrgMembership.STATUS_ACTIVE,
                    },
                )
            TeamMembership.objects.update_or_create(
                team=team,
                user=lead,
                defaults={"team_role": TeamMembership.ROLE_LEAD},
            )
            TeamMembership.objects.update_or_create(
                team=team,
                user=member,
                defaults={"team_role": TeamMembership.ROLE_MEMBER},
            )
        Project.objects.get_or_create(org=org, name="Workspace V2", defaults={"lead": owner})
        for team in Team.objects.filter(org=org):
            ensure_team_room(team)
        for project in Project.objects.filter(org=org):
            ensure_project_room(project)
        acme, _ = Organization.objects.get_or_create(slug="acme", defaults={"name": "Acme"})
        OrgMembership.objects.update_or_create(
            org=acme,
            user=owner,
            defaults={
                "org_role": OrgMembership.ORG_ROLE_OWNER,
                "employment_status": OrgMembership.STATUS_ACTIVE,
            },
        )
        for user in User.objects.filter(email__endswith="@flolabs.local"):
            sync_user_type(user)
        self.stdout.write(self.style.SUCCESS(f"Seeded FloLabs org {org.id}"))
