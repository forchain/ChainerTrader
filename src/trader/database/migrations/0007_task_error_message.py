from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    operations = [
        ops.AddField("TaskStateModel", "error_message", fields.TextField(null=True)),
    ]
