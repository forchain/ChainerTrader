from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class KlineModel(Model):
    id = fields.IntField(primary_key=True)
    exchange = fields.CharField(max_length=32)
    symbol = fields.CharField(max_length=32)
    interval = fields.CharField(max_length=16)
    open_time = fields.IntField()
    open = fields.FloatField()
    high = fields.FloatField()
    low = fields.FloatField()
    close = fields.FloatField()
    close_time = fields.IntField()
    volume = fields.FloatField()
    vol_quote = fields.FloatField()
    trades = fields.IntField()
    vol_taker_base = fields.FloatField()
    vol_taker_quote = fields.FloatField()
    ignore = fields.FloatField(default=0)
    raw_payload = fields.JSONField(null=True)
    ingested_at = fields.DatetimeField(auto_now_add=True)
    source = fields.CharField(max_length=64, default="unknown")

    class Meta:
        table = "klines"
        unique_together = (("exchange", "symbol", "interval", "open_time"),)
        indexes = (("exchange", "symbol", "interval", "open_time"),)


class TaskStateModel(Model):
    task_id = fields.IntField(primary_key=True)
    state = fields.CharField(max_length=32)
    name = fields.CharField(max_length=255, null=True)
    start_time = fields.DatetimeField()
    commission = fields.FloatField(default=0)
    strategy_start_time = fields.IntField(default=0)
    strategy_end_time = fields.IntField(default=0)
    initial_cash = fields.FloatField(default=0)
    config_json = fields.TextField(null=True)
    tret = fields.JSONField(null=True)

    class Meta:
        table = "tasks"


class AvailabilityModel(Model):
    id = fields.IntField(primary_key=True)
    exchange = fields.CharField(max_length=32)
    symbol = fields.CharField(max_length=32)
    interval = fields.CharField(max_length=16)
    earliest_known_open_time = fields.IntField()
    updated_at = fields.IntField()
    source = fields.CharField(max_length=64)

    class Meta:
        table = "availability"
        unique_together = (("exchange", "symbol", "interval"),)
        indexes = (("exchange", "symbol", "interval"),)


class ExecutionStateModel(Model):
    id = fields.IntField(primary_key=True)
    idempotency_key = fields.CharField(max_length=255, unique=True)
    intent_id = fields.CharField(max_length=128)
    operation_id = fields.CharField(max_length=128)
    gateway = fields.CharField(max_length=32)
    staged_execution_mode = fields.CharField(max_length=32)
    symbol = fields.CharField(max_length=32)
    trade_id = fields.CharField(max_length=128, null=True)
    order_role = fields.CharField(max_length=32)
    status = fields.CharField(max_length=32)
    exchange_order_id = fields.CharField(max_length=255, null=True)
    protection_id = fields.CharField(max_length=128, null=True)
    quantity = fields.FloatField(default=0)
    price = fields.FloatField(null=True)
    stop_price = fields.FloatField(null=True)
    take_profit_price = fields.FloatField(null=True)
    raw_payload = fields.JSONField(null=True)
    created_at = fields.IntField(default=0)
    updated_at = fields.IntField(default=0)

    class Meta:
        table = "execution_states"
        indexes = (("symbol", "trade_id"), ("gateway", "staged_execution_mode"), ("intent_id", "operation_id"))
