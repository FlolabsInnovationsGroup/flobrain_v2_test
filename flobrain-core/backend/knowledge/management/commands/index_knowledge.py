from django.core.management.base import BaseCommand, CommandError

from docs_app.models import Document
from knowledge.index import index_source, org_indexing_enabled, request_index
from knowledge.models import KnowledgeChunk
from organizations.models import Organization
from rooms.models import RoomMessage


class Command(BaseCommand):
    help = (
        "Index an org's existing documents and room messages. Requires the org's memory_search flag. "
        "Queues one job per source on the worker; --inline runs them here. Safe to repeat (content hash)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--org", required=True, help="Organization id")
        parser.add_argument("--inline", action="store_true", help="Index in this process instead of queuing")
        parser.add_argument("--limit", type=int, default=None, help="Stop after this many sources")

    def handle(self, *args, **options):
        org = Organization.objects.filter(pk=options["org"]).first()
        if org is None:
            raise CommandError("Organization not found")
        if not org_indexing_enabled(org):
            raise CommandError("memory_search is off for this org; nothing was indexed")

        sources = [
            (KnowledgeChunk.SOURCE_DOC, pk)
            for pk in Document.objects.filter(org=org).values_list("pk", flat=True).iterator()
        ]
        sources += [
            (KnowledgeChunk.SOURCE_ROOM_MESSAGE, pk)
            for pk in RoomMessage.objects.filter(room__org=org, deleted_at__isnull=True)
            .values_list("pk", flat=True)
            .iterator()
        ]
        if options["limit"] is not None:
            sources = sources[: options["limit"]]

        counts = {"indexed": 0, "queued": 0, "skipped": 0}
        for source_type, pk in sources:
            if options["inline"]:
                result = index_source(source_type, pk)
                if result.get("reason") == "not_configured":
                    raise CommandError("Embeddings or the vector store are not configured")
                counts["indexed" if result.get("ok") else "skipped"] += 1
            else:
                result = request_index(source_type, pk)
                if result.get("reason") == "unavailable":
                    raise CommandError("No job worker (JOBS_WORKER_ENABLED is off). Use --inline.")
                counts["queued" if result.get("ok") else "skipped"] += 1
        self.stdout.write(
            f"sources {len(sources)}: indexed {counts['indexed']}, queued {counts['queued']}, skipped {counts['skipped']}"
        )
