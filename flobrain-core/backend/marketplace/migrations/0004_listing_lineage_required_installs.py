import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("marketplace", "0003_listing_lineage_backfill"),
        ("organizations", "0004_org_policy"),
        ("users", "0003_user_v2_profile"),
    ]

    operations = [
        migrations.AlterField(model_name="listing", name="lineage", field=models.UUIDField(db_index=True)),
        migrations.AddConstraint(
            model_name="listing",
            constraint=models.UniqueConstraint(fields=("lineage", "version"), name="one_listing_per_version"),
        ),
        migrations.CreateModel(
            name="Install",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("lineage", models.UUIDField(db_index=True)),
                ("version", models.PositiveIntegerField()),
                (
                    "kind",
                    models.CharField(
                        choices=[("buddy", "Buddy"), ("content_template", "Content template")], max_length=20
                    ),
                ),
                ("target_id", models.UUIDField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "listing",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="copies", to="marketplace.listing"
                    ),
                ),
                (
                    "org",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="listing_installs",
                        to="organizations.organization",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="+", to="users.user"
                    ),
                ),
            ],
            options={
                "db_table": "marketplace_installs",
                "ordering": ["-created_at"],
                "constraints": [models.UniqueConstraint(fields=("kind", "target_id"), name="one_install_per_copy")],
            },
        ),
    ]
