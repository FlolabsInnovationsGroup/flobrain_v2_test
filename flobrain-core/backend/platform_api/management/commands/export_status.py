"""Write the public status page projection (Phase 14f). Serve the file from separate static hosting.

Only platform-wide public incidents and component states; no org data.
"""

import json

from django.core.management.base import BaseCommand

from platform_api.status import COMPONENTS, projection  # noqa: F401  (COMPONENTS kept for importers)


class Command(BaseCommand):
    help = "Write the sanitized status JSON (public platform incidents only)."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True)

    def handle(self, *args, **options):
        data = projection()
        with open(options["out"], "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        self.stdout.write(f"wrote {len(data['incidents'])} incidents")
