from django.core.management.base import BaseCommand
from django.utils import timezone

from content_studio import storage
from exports.models import MemoryExport


class Command(BaseCommand):
    help = "Delete expired memory exports and personal data downloads (run daily)."

    def handle(self, *args, **options):
        done = 0
        for export in MemoryExport.objects.filter(expires_at__lt=timezone.now()).exclude(storage_key=""):
            storage.delete(export.storage_key)
            MemoryExport.objects.filter(pk=export.pk).update(storage_key="")
            done += 1
        from privacy.models import DataExportJob

        for job in DataExportJob.objects.filter(expires_at__lt=timezone.now()).exclude(storage_key=""):
            storage.delete(job.storage_key)
            DataExportJob.objects.filter(pk=job.pk).update(storage_key="")
            done += 1
        self.stdout.write(f"purged {done}")
