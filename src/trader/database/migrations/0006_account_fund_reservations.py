from tortoise import fields, migrations
from tortoise.indexes import Index
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    operations = [
        ops.CreateModel(
            name="AccountFundReservationModel",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("account_key", fields.CharField(max_length=128)),
                ("exchange", fields.CharField(max_length=32)),
                ("credential_id", fields.IntField(null=True)),
                ("user_id", fields.IntField(null=True)),
                ("task_id", fields.IntField()),
                ("asset", fields.CharField(max_length=32)),
                ("reserved_amount", fields.FloatField(default=0)),
                ("spent_amount", fields.FloatField(default=0)),
                ("status", fields.CharField(default="active", max_length=16)),
                ("reason", fields.CharField(max_length=128, null=True)),
                ("created_at", fields.DatetimeField(auto_now_add=True)),
                ("updated_at", fields.DatetimeField(auto_now=True)),
                ("released_at", fields.DatetimeField(null=True)),
            ],
            options={
                "table": "account_fund_reservations",
                "app": "models",
                "indexes": [Index(fields=["account_key", "asset", "status"]), Index(fields=["task_id"]), Index(fields=["user_id"])],
                "pk_attr": "id",
            },
            bases=["Model"],
        ),
    ]
