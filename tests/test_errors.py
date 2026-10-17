from __future__ import annotations

import pytest

from bot.services.downloader.errors import (
    AIError,
    DownloadError,
    TooLargeError,
    UnsupportedError,
    classify_error,
)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("ERROR: Private video. Sign in to confirm", "errors.private"),
        ("This video is age-restricted", "errors.age"),
        ("The uploader has not made this video available in your country", "errors.geo"),
        ("Unsupported URL: https://example.com", "errors.unsupported"),
        ("Video unavailable", "errors.unavailable"),
        ("Connection timed out", "errors.network"),
        ("HTTP Error 403: Forbidden", "errors.forbidden"),
        ("HTTP Error 429: Too Many Requests", "errors.rate_limit"),
        ("Requested format is not available", "errors.format"),
        ("No space left on device", "errors.disk"),
        ("ffmpeg not found", "errors.ffmpeg"),
        ("File is larger than max-filesize", "errors.too_large"),
        ("something unexpected", "errors.unknown"),
    ],
)
def test_error_classification(message, expected):  # noqa: ANN001
    assert classify_error(RuntimeError(message)).key == expected


def test_error_classes():
    assert isinstance(TooLargeError(), DownloadError)
    assert isinstance(UnsupportedError(), DownloadError)
    assert AIError("ai.auth").key == "ai.auth"
    assert DownloadError().key == "errors.unknown"
    assert DownloadError("errors.custom", "detail").detail == "detail"
