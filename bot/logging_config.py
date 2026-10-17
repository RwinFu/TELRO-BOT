"""Logging setup with console and rotating file handlers."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s"
_DATE = "%Y-%m-%d %H:%M:%S"


class HealthCheckFilter(logging.Filter):
    """Hide noisy aiohttp access lines for the health endpoint."""

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - trivial
        return "/health" not in record.getMessage()


def setup_logging(level: str = "INFO", log_file: Path | None = None) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(_FORMAT, _DATE))
    root.addHandler(console)

    if log_file is not None:
        try:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter(_FORMAT, _DATE))
            root.addHandler(file_handler)
        except OSError as exc:  # pragma: no cover - depends on filesystem
            root.warning("Could not create log file %s: %s", log_file, exc)

    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").addFilter(HealthCheckFilter())
    logging.getLogger("yt_dlp").setLevel(logging.WARNING)
