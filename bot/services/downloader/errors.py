"""Download related exceptions and user friendly classification."""

from __future__ import annotations


class BotError(Exception):
    """Base class for errors that can be shown to users."""

    default_key = "errors.unknown"

    def __init__(self, key: str | None = None, detail: str = "") -> None:
        super().__init__(detail or key or self.default_key)
        self.key = key or self.default_key
        self.detail = detail


class DownloadError(BotError):
    default_key = "errors.unknown"


class UnsupportedError(DownloadError):
    default_key = "errors.unsupported"


class TooLargeError(DownloadError):
    default_key = "errors.too_large"


class DownloadCancelled(Exception):
    """Raised from a yt-dlp progress hook when the user cancels."""


class AIError(BotError):
    default_key = "ai.error"


class ImageError(BotError):
    default_key = "image.error"


_ERROR_PATTERNS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("private video", "private", "login required", "sign in", "cookies", "logged in"), "errors.private"),
    (("age", "confirm your age", "age-restricted"), "errors.age"),
    (
        (
            "not available in your country",
            "available in your country",
            "geo restricted",
            "geo-restricted",
            "blocked in your country",
        ),
        "errors.geo",
    ),
    (("unsupported url", "no suitable extractor", "not a valid url"), "errors.unsupported"),
    (("ffmpeg", "ffprobe"), "errors.ffmpeg"),
    (("video unavailable", "has been removed", "does not exist", "not found"), "errors.unavailable"),
    (("timed out", "timeout", "temporary failure", "connection reset", "network is unreachable"), "errors.network"),
    (("http error 403", "forbidden"), "errors.forbidden"),
    (("http error 429", "too many requests", "rate limit"), "errors.rate_limit"),
    (("requested format is not available", "no video formats found"), "errors.format"),
    (("no space left", "disk full"), "errors.disk"),
    (("file is larger than", "too large", "max-filesize"), "errors.too_large"),
)


def classify_error(exc: BaseException) -> DownloadError:
    text = str(exc).lower()
    for patterns, key in _ERROR_PATTERNS:
        if any(pattern in text for pattern in patterns):
            return DownloadError(key, str(exc)[:400])
    return DownloadError("errors.unknown", str(exc)[:400])
