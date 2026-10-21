from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0004_speakers_and_transcript_search"),
    ]

    operations = [
        migrations.AlterField(
            model_name="knowledgechunk",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("doc", "Document"),
                    ("room_message", "Room message"),
                    ("transcript", "Meeting transcript"),
                    ("summary", "Meeting summary"),
                ],
                max_length=16,
            ),
        ),
    ]
