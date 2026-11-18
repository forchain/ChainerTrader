"""Shared domain values: symbols, intervals, klines, operations, and time ranges.

Single source of truth for cross-aggregate value objects. Pure data and rules;
no framework imports.
"""

import calendar
import json
import re
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

"""
Kline intervals
m -> minutes; h -> hours; d -> days; w -> weeks; M -> months

间隔	间隔 值
seconds -> 秒	1s
minutes -> 分钟	1m， 3m， 5m， 15m， 30m
hours -> 小时	1h， 2h， 4h， 6h， 8h， 12h
days -> 天	1d， 3d
weeks -> 周	1w
months -> 月	1M
"""


class Interval(Enum):
    INTERVAL_1s = "1s"
    INTERVAL_1m = "1m"
    INTERVAL_3m = "3m"
    INTERVAL_5m = "5m"
    INTERVAL_15m = "15m"
    INTERVAL_30m = "30m"
    INTERVAL_1h = "1h"
    INTERVAL_2h = "2h"
    INTERVAL_4h = "4h"
    INTERVAL_6h = "6h"
    INTERVAL_8h = "8h"
    INTERVAL_12h = "12h"
    INTERVAL_1d = "1d"
    INTERVAL_3d = "3d"
    INTERVAL_1w = "1w"
    INTERVAL_1M = "1M"


# return seconds
def get_time_duration(interval: Interval) -> int:
    if interval == Interval.INTERVAL_1s:
        return 1
    elif interval == Interval.INTERVAL_1m:
        return int(timedelta(minutes=1).total_seconds())
    elif interval == Interval.INTERVAL_3m:
        return int(timedelta(minutes=3).total_seconds())
    elif interval == Interval.INTERVAL_5m:
        return int(timedelta(minutes=5).total_seconds())
    elif interval == Interval.INTERVAL_15m:
        return int(timedelta(minutes=15).total_seconds())
    elif interval == Interval.INTERVAL_30m:
        return int(timedelta(minutes=30).total_seconds())
    elif interval == Interval.INTERVAL_1h:
        return int(timedelta(hours=1).total_seconds())
    elif interval == Interval.INTERVAL_2h:
        return int(timedelta(hours=2).total_seconds())
    elif interval == Interval.INTERVAL_4h:
        return int(timedelta(hours=4).total_seconds())
    elif interval == Interval.INTERVAL_6h:
        return int(timedelta(hours=6).total_seconds())
    elif interval == Interval.INTERVAL_8h:
        return int(timedelta(hours=8).total_seconds())
    elif interval == Interval.INTERVAL_12h:
        return int(timedelta(hours=12).total_seconds())
    elif interval == Interval.INTERVAL_1d:
        return int(timedelta(days=1).total_seconds())
    elif interval == Interval.INTERVAL_3d:
        return int(timedelta(days=3).total_seconds())
    elif interval == Interval.INTERVAL_1w:
        return int(timedelta(weeks=1).total_seconds())
    elif interval == Interval.INTERVAL_1M:
        return int(timedelta(days=30).total_seconds())


def add_time_duration(cur: int, interval: Interval, num: int) -> int:
    return cur + get_time_duration(interval) * num


class Symbol:
    def __init__(self, symbol: str):
        symbol_list = symbol.split("-")
        if symbol_list and len(symbol_list) == 2:
            self.base = symbol_list[0]
            self.quote = symbol_list[1]
        else:
            self.base = ""
            self.quote = ""

    def name(self):
        return self.base + self.quote

    def is_empty(self):
        return len(self.name()) == 0


class SymbolInterval:
    def __init__(self, symbol: str, interval: Interval):
        self.sy = Symbol(symbol)
        self.interval = interval

    def name(self):
        return self.symbol() + "-" + self.interval.value

    def symbol(self):
        return self.sy.name()

    def is_empty(self):
        return self.sy.is_empty() or len(self.interval.value) == 0


PRIMARY_KEY = "open_time"


class Kline:
    def __init__(
        self,
        open_time: int,
        open: float,
        high: float,
        low: float,
        close: float,
        close_time: int,
        volume: float,
        vol_quote: float,
        trades: int,
        vol_taker_base: float,
        vol_taker_quote: float,
        ignore: float = 0,
    ):
        self.open_time = open_time
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.close_time = close_time
        self.volume = volume
        self.vol_quote = vol_quote
        self.trades = trades
        self.vol_taker_base = vol_taker_base
        self.vol_taker_quote = vol_taker_quote
        self.ignore = ignore

    def to_dict(self):
        return {
            "open_datetime": f"{self.open_datetime()}",
            PRIMARY_KEY: self.open_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "close_datetime": f"{self.close_datetime()}",
            "close_time": self.close_time,
            "volume": self.volume,
            "vol_quote": self.vol_quote,
            "trades": self.trades,
            "vol_taker_base": self.vol_taker_base,
            "vol_taker_quote": self.vol_taker_quote,
            "ignore": self.ignore,
        }

    def to_json(self):
        return json.dumps(self.to_dict(), indent=4)

    def open_datetime(self):
        return datetime.fromtimestamp(self.open_time)

    def close_datetime(self):
        return datetime.fromtimestamp(self.close_time)

    def key(self):
        return self.open_time


def parse_kline(data) -> Kline:
    return Kline(
        open_time=data[PRIMARY_KEY],
        open=data["open"],
        high=data["high"],
        low=data["low"],
        close=data["close"],
        close_time=data["close_time"],
        volume=data["volume"],
        vol_quote=data["vol_quote"],
        trades=data["trades"],
        vol_taker_base=data["vol_taker_base"],
        vol_taker_quote=data["vol_taker_quote"],
        ignore=data["ignore"],
    )


class OperateType(Enum):
    UNKNOWN = 0
    BUY = 1
    SELL = 2
    LONG = 3
    SHORT = 4
    CLOSE = 5
    RISK_UPDATE = 6


def parse_operate_type(name):
    if name is None:
        return OperateType.UNKNOWN

    if name == OperateType.UNKNOWN.name:
        return OperateType.UNKNOWN
    elif name == OperateType.BUY.name:
        return OperateType.BUY
    elif name == OperateType.SELL.name:
        return OperateType.SELL
    elif name == OperateType.LONG.name:
        return OperateType.LONG
    elif name == OperateType.SHORT.name:
        return OperateType.SHORT
    elif name == OperateType.CLOSE.name:
        return OperateType.CLOSE
    elif name == OperateType.RISK_UPDATE.name:
        return OperateType.RISK_UPDATE

    return OperateType.UNKNOWN


class Operate:
    def __init__(self, otype: OperateType, dtime: int, price: float = 0):
        self.otype = otype
        self.dtime = dtime
        self.price = price

    def to_dict(self):
        payload = {
            "type": self.otype.name if self.otype else "UNKNOWN",
            "datetime": self.dtime,
            "price": self.price if self.price is not None else 0.0,
        }
        for name in (
            "stop_loss",
            "take_profit",
            "risk_reward_ratio",
            "signal_event_id",
            "signal_number",
            "trigger_reason",
            "breakeven_old_stop",
            "breakeven_new_stop",
            "breakeven_step",
            "signal_metadata",
            "divergence_metadata",
            "framework_trade",
        ):
            if hasattr(self, name):
                payload[name] = getattr(self, name)
        return payload


def parse_opts(parsed_list) -> list[Operate]:
    if not parsed_list:
        return []

    ret = []
    for opc in parsed_list:
        op = Operate(parse_operate_type(opc["type"]), opc["datetime"], opc["price"])
        for name in (
            "stop_loss",
            "take_profit",
            "risk_reward_ratio",
            "signal_event_id",
            "signal_number",
            "trigger_reason",
            "breakeven_old_stop",
            "breakeven_new_stop",
            "breakeven_step",
            "signal_metadata",
            "divergence_metadata",
            "framework_trade",
        ):
            if name in opc:
                setattr(op, name, opc[name])
        ret.append(op)

    return ret


RELATIVE_DURATION_PATTERN = re.compile(
    r"^[+-]?(?P<amount>\d+)(?P<unit>[hdwmy])$",
    re.IGNORECASE,
)

DEFAULT_START_TIME = datetime(2000, 1, 1, 0, 0, 0)


def parse_relative_duration(value: Any) -> tuple[int, str] | None:
    """Parse relative duration strings like '1y', '365d', '-30d', '6m', '2w', '24h'.

    Returns (amount, unit) where unit is lowercased ('y', 'm', 'w', 'd', 'h').
    Returns None if value is not a relative duration string.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    match = RELATIVE_DURATION_PATTERN.fullmatch(stripped)
    if not match:
        return None
    return int(match.group("amount")), match.group("unit").lower()


def shift_months(value: datetime, months: int) -> datetime:
    """Shift datetime by months with month-end day clamping (handles leap years)."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def offset_time(value: datetime, amount: int, unit: str) -> datetime:
    """Offset datetime by the specified amount and unit (positive or negative)."""
    unit = unit.lower()
    if unit == "y":
        return shift_months(value, amount * 12)
    if unit == "m":
        return shift_months(value, amount)
    if unit == "w":
        return value + timedelta(weeks=amount)
    if unit == "d":
        return value + timedelta(days=amount)
    if unit == "h":
        return value + timedelta(hours=amount)
    raise ValueError(f"Unsupported duration unit: {unit}")


def offset_time_backward(value: datetime, amount: int, unit: str) -> datetime:
    """Offset datetime backward by the specified amount and unit."""
    return offset_time(value, -abs(amount), unit)


def parse_time_point(value: Any) -> datetime | tuple[int, str] | None:
    """Parse a time point into datetime, relative duration tuple, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value))
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        rel = parse_relative_duration(stripped)
        if rel is not None:
            return rel
        if stripped.isdigit():
            return datetime.fromtimestamp(int(stripped))
        try:
            return datetime.strptime(stripped, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                return datetime.fromisoformat(stripped)
            except ValueError:
                raise ValueError(f"Unsupported time format: {value}")
    raise ValueError(f"Unsupported time value type: {type(value)}")


def resolve_datetime_range(
    start_val: Any,
    end_val: Any,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Resolve start_time and end_time to concrete datetimes.

    - end_time defaults to now if omitted or None.
    - If end_time is relative, it is resolved backward from now.
    - start_time defaults to 2000-01-01 00:00:00 if omitted or None.
    - If start_time is relative, it is resolved backward from end_time.
    """
    current_time = now if now is not None else datetime.now()

    # Resolve end_time first
    end_point = parse_time_point(end_val)
    if end_point is None:
        end_dt = current_time
    elif isinstance(end_point, tuple):
        amount, unit = end_point
        end_dt = offset_time_backward(current_time, amount, unit)
    else:
        end_dt = end_point

    # Resolve start_time relative to end_time if relative
    start_point = parse_time_point(start_val)
    if start_point is None:
        start_dt = DEFAULT_START_TIME
    elif isinstance(start_point, tuple):
        amount, unit = start_point
        start_dt = offset_time_backward(end_dt, amount, unit)
    else:
        start_dt = start_point

    return start_dt, end_dt


def resolve_time_range(
    start_val: Any,
    end_val: Any,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Resolve start_time and end_time into integer timestamps."""
    start_dt, end_dt = resolve_datetime_range(start_val, end_val, now=now)
    return int(start_dt.timestamp()), int(end_dt.timestamp())
