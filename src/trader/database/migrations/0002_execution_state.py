import functools
from json import dumps, loads

from tortoise import fields, migrations
from tortoise.indexes import Index
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    operations = [
        ops.CreateModel(
            name="ExecutionStateModel",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("idempotency_key", fields.CharField(max_length=255, unique=True)),
                ("intent_id", fields.CharField(max_length=128)),
                ("operation_id", fields.CharField(max_length=128)),
                ("gateway", fields.CharField(max_length=32)),
                ("staged_execution_mode", fields.CharField(max_length=32)),
                ("symbol", fields.CharField(max_length=32)),
                ("trade_id", fields.CharField(null=True, max_length=128)),
                ("order_role", fields.CharField(max_length=32)),
                ("status", fields.CharField(max_length=32)),
                ("exchange_order_id", fields.CharField(null=True, max_length=255)),
                ("protection_id", fields.CharField(null=True, max_length=128)),
                ("quantity", fields.FloatField(default=0)),
                ("price", fields.FloatField(null=True)),
                ("stop_price", fields.FloatField(null=True)),
                ("take_profit_price", fields.FloatField(null=True)),
                ("raw_payload", fields.JSONField(null=True, encoder=functools.partial(dumps, separators=(",", ":")), decoder=loads)),
                ("created_at", fields.IntField(default=0)),
                ("updated_at", fields.IntField(default=0)),
            ],
            options={
                "table": "execution_states",
                "app": "models",
                "indexes": [
                    Index(fields=["symbol", "trade_id"]),
                    Index(fields=["gateway", "staged_execution_mode"]),
                    Index(fields=["intent_id", "operation_id"]),
                ],
                "pk_attr": "id",
            },
            bases=["Model"],
        ),
    ]
