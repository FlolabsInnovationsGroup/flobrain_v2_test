from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("content_studio", "0005_review_fixes"),
    ]

    operations = [
        migrations.AddField(
            model_name="mediaasset",
            name="transcript_status",
            field=models.CharField(blank=True, default="", max_length=8),
        ),
    ]
