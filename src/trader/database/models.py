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
    user_id = fields.IntField(null=True)
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
        indexes = (("user_id",),)


class UserModel(Model):
    id = fields.IntField(primary_key=True)
    username = fields.CharField(max_length=32, unique=True)
    password_hash = fields.TextField()
    role = fields.CharField(max_length=16, default="user")
    status = fields.CharField(max_length=16, default="active")
    must_change_password = fields.BooleanField(default=False)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    last_login_at = fields.DatetimeField(null=True)

    class Meta:
        table = "users"
        indexes = (("role",), ("status",))


class SessionModel(Model):
    id = fields.IntField(primary_key=True)
    session_hash = fields.CharField(max_length=64, unique=True)
    user_id = fields.IntField()
    expires_at = fields.DatetimeField()
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "sessions"
        indexes = (("user_id",), ("expires_at",))


class ExchangeCredentialModel(Model):
    id = fields.IntField(primary_key=True)
    user_id = fields.IntField()
    exchange = fields.CharField(max_length=32)
    label = fields.CharField(max_length=64, default="default")
    encrypted_api_key = fields.TextField()
    encrypted_api_secret = fields.TextField()
    masked_api_key = fields.CharField(max_length=64, default="")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "exchange_credentials"
        unique_together = (("user_id", "exchange", "label"),)
        indexes = (("user_id", "exchange"),)


class StrategyConfigModel(Model):
    id = fields.IntField(primary_key=True)
    user_id = fields.IntField()
    name = fields.CharField(max_length=128)
    strategy_name = fields.CharField(max_length=128)
    symbol = fields.CharField(max_length=32)
    interval = fields.CharField(max_length=16)
    params = fields.JSONField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "strategy_configs"
        indexes = (("user_id",), ("user_id", "strategy_name"))


class AvailabilityModel(Model):
    id = fields.IntField(primary_key=True)
    exchange = fields.CharField(max_length=32)
    symbol = fields.CharField(max_length=32)
    interval = fields.CharField(max_length=16)
    earliest_known_open_time = fields.IntField(null=True)
    cached_start_open_time = fields.IntField(null=True)
    cached_end_open_time = fields.IntField(null=True)
    updated_at = fields.IntField()
    source = fields.CharField(max_length=64)

    class Meta:
        table = "availability"
        unique_together = (("exchange", "symbol", "interval"),)
        indexes = (("exchange", "symbol", "interval"),)


class ExecutionStateModel(Model):
    id = fields.IntField(primary_key=True)
    task_id = fields.IntField(null=True)
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
        indexes = (("task_id", "symbol", "trade_id"), ("gateway", "staged_execution_mode"), ("intent_id", "operation_id"))
