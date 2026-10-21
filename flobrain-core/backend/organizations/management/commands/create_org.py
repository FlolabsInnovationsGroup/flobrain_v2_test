"""Create an organization and its owner from the command line: the first org of a new install
(local or production), before anyone can open the platform console.

    python manage.py create_org --name "FloLabs" --slug flolabs --owner-email you@example.com

A new owner gets a one-time temporary password (printed once, must be changed at first sign-in).
An existing account just becomes the owner. Feature flags stay off unless ``--all-features``.
"""

import secrets

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from console.views import EMAIL_RE, RESERVED_SLUGS, SLUG_RE
from organizations.models import OrgMembership, Organization
from users.models import User

FEATURES = [
    "ai_actions", "api_access", "assign_suggestions", "auto_reports", "budgets", "buddies", "byok",
    "content_studio", "live_translation", "memory_search", "realtime", "room_ai", "scheduled_agents",
    "social_publishing", "voice_video", "webhooks", "learning", "commissions", "pulse",
    "integrations", "meeting_bot", "cockpit", "status_page", "external_agents", "public_portfolio",
]


class Command(BaseCommand):
    help = "Create an organization and its owner (first org of an install)."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True)
        parser.add_argument("--slug", required=True, help="the workspace address: /w/<slug>")
        parser.add_argument("--owner-email", required=True)
        parser.add_argument("--owner-name", default="")
        parser.add_argument("--all-features", action="store_true", help="switch every feature flag on")
        parser.add_argument("--platform-admin", action="store_true", help="also make the owner a FloLabs platform admin")

    def handle(self, *args, **opts):
        name, slug, email = opts["name"].strip(), opts["slug"].strip(), opts["owner_email"].strip().lower()
        if not 2 <= len(name) <= 200:
            raise CommandError("--name must be 2 to 200 characters")
        if not SLUG_RE.fullmatch(slug) or slug in RESERVED_SLUGS:
            raise CommandError("--slug must be 3 to 50 lowercase letters, digits and dashes, and not a reserved word")
        if not EMAIL_RE.fullmatch(email):
            raise CommandError("--owner-email must be a valid email")
        if Organization.objects.filter(slug=slug).exists():
            raise CommandError(f"An organization already uses /w/{slug}")
        temp = None
        with transaction.atomic():
            org = Organization.objects.create(
                name=name, slug=slug, settings={"flags": {key: True for key in FEATURES}} if opts["all_features"] else {}
            )
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                temp = secrets.token_urlsafe(12)
                user = User.objects.create(
                    email=email, username=(opts["owner_name"] or email.split("@")[0])[:150],
                    password_hash=make_password(temp), must_change_password=True,
                )
            if opts["platform_admin"] and not user.is_platform_admin:
                user.is_platform_admin = True
                user.save(update_fields=["is_platform_admin"])
            OrgMembership.objects.create(
                org=org, user=user, org_role=OrgMembership.ORG_ROLE_OWNER,
                employment_status=OrgMembership.STATUS_ACTIVE, status_changed_at=timezone.now(),
            )
        self.stdout.write(self.style.SUCCESS(f"Created {name}: /w/{slug}"))
        self.stdout.write(f"Owner: {user.email}")
        if temp:
            self.stdout.write(f"Temporary password (shown once, change it at first sign-in): {temp}")
        else:
            self.stdout.write("The owner already had an account: sign in with its password.")
