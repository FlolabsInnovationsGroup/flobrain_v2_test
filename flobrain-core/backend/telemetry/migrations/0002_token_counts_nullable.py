from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("telemetry", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="usageevent",
            name="total_tokens",
            field=models.PositiveIntegerField(blank=True, default=0, null=True),
        ),
    ]
