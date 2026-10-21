from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("marketplace", "0001_initial"),
        ("organizations", "0004_org_policy"),
        ("users", "0003_user_v2_profile"),
    ]

    operations = [
        migrations.AddField(model_name="listing", name="lineage", field=models.UUIDField(null=True)),
        migrations.AddField(model_name="listing", name="version", field=models.PositiveIntegerField(default=1)),
        migrations.AddField(
            model_name="listing", name="changelog", field=models.CharField(blank=True, default="", max_length=500)
        ),
        migrations.AlterField(
            model_name="listing",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "pending"),
                    ("approved", "approved"),
                    ("rejected", "rejected"),
                    ("withdrawn", "withdrawn"),
                    ("superseded", "superseded"),
                ],
                default="pending",
                max_length=10,
            ),
        ),
    ]
