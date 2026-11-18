from tortoise import migrations
from tortoise.migrations import operations as ops
import functools
from json import dumps, loads
from tortoise import fields
from tortoise.indexes import Index


class Migration(migrations.Migration):
    initial = True

    operations = [
        ops.CreateModel(
            name="AvailabilityModel",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("exchange", fields.CharField(max_length=32)),
                ("symbol", fields.CharField(max_length=32)),
                ("interval", fields.CharField(max_length=16)),
                ("earliest_known_open_time", fields.IntField()),
                ("updated_at", fields.IntField()),
                ("source", fields.CharField(max_length=64)),
            ],
            options={
                "table": "availability",
                "app": "models",
                "unique_together": (("exchange", "symbol", "interval"),),
                "indexes": [Index(fields=["exchange", "symbol", "interval"])],
                "pk_attr": "id",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="KlineModel",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("exchange", fields.CharField(max_length=32)),
                ("symbol", fields.CharField(max_length=32)),
                ("interval", fields.CharField(max_length=16)),
                ("open_time", fields.IntField()),
                ("open", fields.FloatField()),
                ("high", fields.FloatField()),
                ("low", fields.FloatField()),
                ("close", fields.FloatField()),
                ("close_time", fields.IntField()),
                ("volume", fields.FloatField()),
                ("vol_quote", fields.FloatField()),
                ("trades", fields.IntField()),
                ("vol_taker_base", fields.FloatField()),
                ("vol_taker_quote", fields.FloatField()),
                ("ignore", fields.FloatField(default=0)),
                ("raw_payload", fields.JSONField(null=True, encoder=functools.partial(dumps, separators=(",", ":")), decoder=loads)),
                ("ingested_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
                ("source", fields.CharField(default="unknown", max_length=64)),
            ],
            options={
                "table": "klines",
                "app": "models",
                "unique_together": (("exchange", "symbol", "interval", "open_time"),),
                "indexes": [Index(fields=["exchange", "symbol", "interval", "open_time"])],
                "pk_attr": "id",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="TaskStateModel",
            fields=[
                ("task_id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("state", fields.CharField(max_length=32)),
                ("name", fields.CharField(null=True, max_length=255)),
                ("start_time", fields.DatetimeField(auto_now=False, auto_now_add=False)),
                ("commission", fields.FloatField(default=0)),
                ("strategy_start_time", fields.IntField(default=0)),
                ("strategy_end_time", fields.IntField(default=0)),
                ("initial_cash", fields.FloatField(default=0)),
                ("config_json", fields.TextField(null=True, unique=False)),
                ("tret", fields.JSONField(null=True, encoder=functools.partial(dumps, separators=(",", ":")), decoder=loads)),
            ],
            options={"table": "tasks", "app": "models", "pk_attr": "task_id"},
            bases=["Model"],
        ),
    ]
