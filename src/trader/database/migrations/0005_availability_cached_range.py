from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    operations = [
        ops.AlterField("AvailabilityModel", "earliest_known_open_time", fields.IntField(null=True)),
        ops.AddField("AvailabilityModel", "cached_start_open_time", fields.IntField(null=True)),
        ops.AddField("AvailabilityModel", "cached_end_open_time", fields.IntField(null=True)),
    ]
