from django.core.management.base import BaseCommand, CommandError

from users.models import User


class Command(BaseCommand):
    help = "Grant or revoke the FloLabs platform admin flag for a user, by email."

    def add_arguments(self, parser):
        parser.add_argument("email", type=str)
        parser.add_argument(
            "--revoke",
            action="store_true",
            help="Remove the flag instead of granting it.",
        )

    def handle(self, *args, **options):
        email = options["email"]
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist as exc:
            raise CommandError(f"No user with email {email}") from exc

        user.is_platform_admin = not options["revoke"]
        user.save(update_fields=["is_platform_admin"])
        state = "granted" if user.is_platform_admin else "revoked"
        self.stdout.write(self.style.SUCCESS(f"Platform admin {state} for {email}"))
