from __future__ import annotations

import pytest

from bot.utils.formatting import (
    compact_number,
    human_bytes,
    human_duration,
    human_eta,
    human_speed,
    percent,
    progress_bar,
    quality_label,
    truncate,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0 B"),
        (512, "512 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (50 * 1024 * 1024, "50.0 MB"),
        (2 * 1024 * 1024 * 1024, "2.0 GB"),
        (None, "—"),
    ],
)
def test_human_bytes(value, expected):  # noqa: ANN001
    assert human_bytes(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "00:00"), (5, "00:05"), (65, "01:05"), (3661, "01:01:01"), (90061, "1d 01:01")],
)
def test_human_duration(value, expected):  # noqa: ANN001
    assert human_duration(value) == expected


def test_human_speed_and_eta():
    assert human_speed(1024 * 1024) == "1.0 MB/s"
    assert human_speed(0) == "—"
    assert human_eta(30) == "30s"
    assert human_eta(120) == "2m 00s"
    assert human_eta(3700) == "1h 01m"


def test_progress_bar():
    assert progress_bar(0) == "▱" * 10
    assert progress_bar(50) == "▰" * 5 + "▱" * 5
    assert progress_bar(100) == "▰" * 10
    assert progress_bar(150) == "▰" * 10


def test_truncate_and_compact():
    assert truncate("hello world", 5) == "hell…"
    assert truncate("short", 10) == "short"
    assert compact_number(999) == "999"
    assert compact_number(1500) == "1.5K"
    assert compact_number(2_500_000) == "2.5M"
    assert compact_number(None) == "—"


def test_labels_and_percent():
    assert quality_label(1080) == "FHD"
    assert quality_label(720) == "HD"
    assert quality_label(None) == "Audio"
    assert percent(5, 10) == 50
    assert percent(1, 0) == 0
