from tortoise import fields, migrations
from tortoise.indexes import Index
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    operations = [
        ops.AddField("ExecutionStateModel", "task_id", fields.IntField(null=True)),
        ops.AddIndex(
            "ExecutionStateModel",
            Index(fields=["task_id", "symbol", "trade_id"]),
        ),
    ]
