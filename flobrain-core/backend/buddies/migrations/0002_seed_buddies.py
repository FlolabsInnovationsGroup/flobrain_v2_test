"""Seed the built-in buddies into the FloLabs org only (spec 6.10). No-op when that org is absent.

Reversible: removes only built-in rows that were never edited away from built-in.
"""

from django.conf import settings
from django.db import migrations


def _slugs():
    raw = getattr(settings, "BUDDY_SEED_ORG_SLUGS", "flolabs") or ""
    return [s.strip() for s in raw.split(",") if s.strip()]


def seed(apps, schema_editor):
    from buddies.seeds import seed_org

    Organization = apps.get_model("organizations", "Organization")
    Buddy = apps.get_model("buddies", "Buddy")
    for org in Organization.objects.filter(slug__in=_slugs()):
        seed_org(org, Buddy=Buddy)


def unseed(apps, schema_editor):
    from buddies.seeds import BUILTIN_BUDDIES

    Organization = apps.get_model("organizations", "Organization")
    Buddy = apps.get_model("buddies", "Buddy")
    Buddy.objects.filter(
        org__in=Organization.objects.filter(slug__in=_slugs()),
        is_builtin=True,
        slug__in=[b["slug"] for b in BUILTIN_BUDDIES],
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("buddies", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
