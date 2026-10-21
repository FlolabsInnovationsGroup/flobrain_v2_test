"""Existing listings are version 1 of their own lineage. A data step on its own (see tasks/0003)."""

from django.db import migrations


def set_lineage(apps, schema_editor):
    Listing = apps.get_model("marketplace", "Listing")
    for listing in Listing.objects.filter(lineage__isnull=True).only("id"):
        Listing.objects.filter(pk=listing.pk).update(lineage=listing.pk)


class Migration(migrations.Migration):

    dependencies = [("marketplace", "0002_listing_versions")]

    operations = [migrations.RunPython(set_lineage, migrations.RunPython.noop)]
