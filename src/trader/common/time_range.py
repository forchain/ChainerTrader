import calendar
import re
from datetime import datetime, timedelta
from typing import Any

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
