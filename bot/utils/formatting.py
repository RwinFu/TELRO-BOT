"""Formatting helpers: sizes, durations, progress bars and truncation."""

from __future__ import annotations

import math
import re

from bot.constants import QUALITY_LABELS

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def human_bytes(size: float | int | None, *, precision: int | None = None) -> str:
    """Return a compact human readable size (e.g. ``24.6 MB``)."""
    if size is None or size < 0:
        return "—"
    value = float(size)
    if value < 1024:
        return f"{int(value)} B"
    index = 0
    while value >= 1024 and index < len(_UNITS) - 1:
        value /= 1024
        index += 1
    if precision is None:
        precision = 0 if value >= 100 else 1
    return f"{value:.{precision}f} {_UNITS[index]}"


def human_duration(seconds: float | int | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02d}:{minutes:02d}"
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def human_speed(bytes_per_second: float | int | None) -> str:
    if not bytes_per_second or bytes_per_second <= 0:
        return "—"
    return f"{human_bytes(bytes_per_second)}/s"


def human_eta(seconds: float | int | None) -> str:
    if seconds is None or seconds <= 0 or math.isinf(seconds) or math.isnan(seconds):
        return "—"
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60):02d}s"
    return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60):02d}m"


def progress_bar(percent: float, width: int = 10) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = int(round(percent / 100 * width))
    return "▰" * filled + "▱" * (width - filled)


def quality_label(height: int | None) -> str:
    if not height:
        return "Audio"
    return QUALITY_LABELS.get(int(height), f"{int(height)}p")


def truncate(text: str, limit: int, suffix: str = "…") -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(suffix))].rstrip() + suffix


def compact_number(value: int | None) -> str:
    if value is None:
        return "—"
    value = int(value)
    if value < 1000:
        return str(value)
    if value < 1_000_000:
        return f"{value / 1000:.1f}K".replace(".0K", "K")
    if value < 1_000_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".0M", "M")
    return f"{value / 1_000_000_000:.1f}B".replace(".0B", "B")


def parse_int(value: str | None, default: int = 0) -> int:
    if not value:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def percent(done: float | None, total: float | None) -> float:
    if not total or total <= 0 or done is None:
        return 0.0
    return max(0.0, min(100.0, done / total * 100))
