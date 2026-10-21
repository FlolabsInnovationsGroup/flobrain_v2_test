from django.db import migrations


def sync(apps, schema_editor):
    from actions.registry import TOOLS

    ToolDefinition = apps.get_model("actions", "ToolDefinition")
    for key, tool in TOOLS.items():
        ToolDefinition.objects.update_or_create(
            key=key,
            defaults={
                "perm_key": tool["perm_key"],
                "json_schema": tool["schema"],
                "risk": tool["risk"],
                "requires_approval": tool["risk"] != "read",
            },
        )


class Migration(migrations.Migration):
    dependencies = [("actions", "0002_sync_tools")]
    operations = [migrations.RunPython(sync, migrations.RunPython.noop)]
