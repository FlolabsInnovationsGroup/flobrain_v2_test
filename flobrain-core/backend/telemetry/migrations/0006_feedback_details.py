from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("telemetry", "0005_budget_scopes_and_surface"),
    ]

    operations = [
        migrations.AddField(
            model_name="feedbackitem",
            name="browser",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="feedbackitem",
            name="screenshot_note",
            field=models.TextField(blank=True, default=""),
        ),
    ]
