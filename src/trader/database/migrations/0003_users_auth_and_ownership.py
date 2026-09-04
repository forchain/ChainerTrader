import functools
from json import dumps, loads

from tortoise import fields, migrations
from tortoise.indexes import Index
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    operations = [
        ops.AddField("TaskStateModel", "user_id", fields.IntField(null=True)),
        ops.CreateModel(
            name="UserModel",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("username", fields.CharField(max_length=32, unique=True)),
                ("password_hash", fields.TextField()),
                ("role", fields.CharField(default="user", max_length=16)),
                ("status", fields.CharField(default="active", max_length=16)),
                ("must_change_password", fields.BooleanField(default=False)),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
                ("updated_at", fields.DatetimeField(auto_now=True, auto_now_add=False)),
                ("last_login_at", fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
            ],
            options={
                "table": "users",
                "app": "models",
                "indexes": [Index(fields=["role"]), Index(fields=["status"])],
                "pk_attr": "id",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="SessionModel",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("session_hash", fields.CharField(max_length=64, unique=True)),
                ("user_id", fields.IntField()),
                ("expires_at", fields.DatetimeField(auto_now=False, auto_now_add=False)),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
            ],
            options={
                "table": "sessions",
                "app": "models",
                "indexes": [Index(fields=["user_id"]), Index(fields=["expires_at"])],
                "pk_attr": "id",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="ExchangeCredentialModel",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("user_id", fields.IntField()),
                ("exchange", fields.CharField(max_length=32)),
                ("label", fields.CharField(default="default", max_length=64)),
                ("encrypted_api_key", fields.TextField()),
                ("encrypted_api_secret", fields.TextField()),
                ("masked_api_key", fields.CharField(default="", max_length=64)),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
                ("updated_at", fields.DatetimeField(auto_now=True, auto_now_add=False)),
            ],
            options={
                "table": "exchange_credentials",
                "app": "models",
                "unique_together": (("user_id", "exchange", "label"),),
                "indexes": [Index(fields=["user_id", "exchange"])],
                "pk_attr": "id",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="StrategyConfigModel",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("user_id", fields.IntField()),
                ("name", fields.CharField(max_length=128)),
                ("strategy_name", fields.CharField(max_length=128)),
                ("symbol", fields.CharField(max_length=32)),
                ("interval", fields.CharField(max_length=16)),
                ("params", fields.JSONField(null=True, encoder=functools.partial(dumps, separators=(",", ":")), decoder=loads)),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
                ("updated_at", fields.DatetimeField(auto_now=True, auto_now_add=False)),
            ],
            options={
                "table": "strategy_configs",
                "app": "models",
                "indexes": [Index(fields=["user_id"]), Index(fields=["user_id", "strategy_name"])],
                "pk_attr": "id",
            },
            bases=["Model"],
        ),
    ]
