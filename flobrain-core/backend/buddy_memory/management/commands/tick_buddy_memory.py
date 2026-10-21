from django.core.management.base import BaseCommand

from buddy_memory.services import purge


class Command(BaseCommand):
    help = "Delete buddy memories past their organization's retention and old declined hashes. Run daily; safe to repeat."

    def handle(self, *args, **options):
        result = purge()
        self.stdout.write(f"deleted {result['memories']} memories, {result['declined']} declined hashes")
