"""Data step on its own, so PostgreSQL commits the schema change (and its deferred index and
foreign-key work) before rows are updated. Mixing both in one transaction fails with
"cannot CREATE INDEX ... because it has pending trigger events" on a database that has tasks."""

from django.db import migrations, models


def backfill(apps, schema_editor):
    """Done tasks get completed_at from their last update; columns get positions by age."""
    Task = apps.get_model("tasks", "Task")
    Task.objects.filter(status="done", completed_at__isnull=True).update(completed_at=models.F("updated_at"))
    last = {}
    for task in Task.objects.order_by("org_id", "status", "created_at").only("id", "org_id", "status"):
        key = (task.org_id, task.status)
        last[key] = last.get(key, -1) + 1
        Task.objects.filter(pk=task.pk).update(position=last[key])


class Migration(migrations.Migration):

    dependencies = [("tasks", "0002_task_priority_position_room_reminders")]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
