from __future__ import annotations

import pytest

from bot.services.downloader.errors import DownloadCancelled
from bot.services.downloader.manager import DownloadJob


def job() -> DownloadJob:
    return DownloadJob(id="abcd1234", user_id=1, chat_id=1, lang="fa", platform="youtube", quality="720")


def test_progress_hook_updates_fields():
    item = job()
    item.progress_hook(
        {
            "status": "downloading",
            "downloaded_bytes": 5 * 1024 * 1024,
            "total_bytes": 10 * 1024 * 1024,
            "speed": 2 * 1024 * 1024,
            "eta": 3,
        }
    )
    assert item.status == "downloading"
    assert item.percent_value == 50
    assert item.eta == 3
    item.progress_hook({"status": "finished"})
    assert item.status == "processing"


def test_progress_hook_honours_cancel():
    item = job()
    item.cancelled = True
    with pytest.raises(DownloadCancelled):
        item.progress_hook({"status": "downloading"})


def test_progress_without_total():
    item = job()
    item.update_progress(1024, None, 512)
    assert item.percent_value == 0
    assert item.downloaded == 1024


def test_log_buffer_is_bounded():
    item = job()
    for index in range(60):
        item.append_log(f"line {index}")
    assert len(item.ytdlp_log) == 40
    assert item.ytdlp_log[-1] == "line 59"
