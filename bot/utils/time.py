"""Time helpers used by the database and handlers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def fmt_date(timestamp: int | None, *, with_time: bool = False) -> str:
    if not timestamp:
        return "—"
    dt = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
    if with_time:
        return dt.strftime("%Y-%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d")


def fmt_remaining(until: int | None) -> str:
    if not until:
        return "—"
    delta = int(until - now_ts())
    if delta <= 0:
        return "0"
    days, rem = divmod(delta, 86400)
    hours = rem // 3600
    if days:
        return f"{days}d {hours}h"
    minutes = rem // 60
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def add_days(days: int) -> int:
    return int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp())


def start_of_day_ts() -> int:
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return int(start.timestamp())


def parse_date(value: str | None) -> int | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return int(datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    return None
