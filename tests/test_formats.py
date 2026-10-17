from __future__ import annotations

import pytest

from bot.services.downloader.formats import (
    MediaInfo,
    QualityOption,
    audio_format_selector,
    build_qualities,
    format_selector,
    quality_cache_key,
)


@pytest.fixture()
def info() -> dict:
    return {
        "id": "vid123",
        "extractor_key": "Youtube",
        "title": "Test video",
        "duration": 600,
        "formats": [
            {
                "height": 1080,
                "ext": "mp4",
                "vcodec": "avc1.4d401f",
                "acodec": "none",
                "filesize": 5_000_000,
                "tbr": 2500,
                "fps": 30,
            },
            {
                "height": 720,
                "ext": "mp4",
                "vcodec": "avc1.4d401f",
                "acodec": "mp4a.40.2",
                "filesize": 3_000_000,
                "tbr": 1200,
            },
            {
                "height": 360,
                "ext": "mp4",
                "vcodec": "avc1",
                "acodec": "none",
                "filesize": 800_000,
                "tbr": 500,
            },
            {
                "height": None,
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "filesize": 1_000_000,
                "tbr": 128,
            },
            {
                "height": 1080,
                "ext": "webm",
                "vcodec": "vp9",
                "acodec": "none",
                "filesize": 4_000_000,
                "tbr": 2000,
            },
        ],
    }


def test_build_qualities(info):
    qualities, audio_size = build_qualities(info)
    heights = [option.height for option in qualities if not option.is_audio]
    assert heights == [1080, 720, 360]
    assert audio_size == 1_000_000
    assert qualities[0].size == 6_000_000
    assert qualities[-1].is_audio
    assert qualities[-1].size == 1_000_000


def test_media_info_lookup():
    media = MediaInfo(
        url="https://youtube.com/watch?v=x",
        platform="youtube",
        media_id="x",
        title="t",
        qualities=[QualityOption(1080, "FHD", 5_000_000), QualityOption(0, "MP3", 1_000_000, is_audio=True)],
    )
    assert media.best.height == 1080
    assert media.find("1080").size == 5_000_000
    assert media.find("audio").is_audio
    assert media.find("240") is None
    assert media.target == media.url


def test_payload_roundtrip():
    media = MediaInfo(
        url="https://open.spotify.com/track/1",
        platform="spotify",
        media_id="1",
        title="Song",
        download_url="https://youtube.com/watch?v=2",
        qualities=[QualityOption(0, "MP3", 1000, is_audio=True)],
    )
    restored = MediaInfo.from_payload(media.to_payload())
    assert restored.title == "Song"
    assert restored.platform == "spotify"
    assert restored.download_url == "https://youtube.com/watch?v=2"
    assert restored.target == "https://youtube.com/watch?v=2"
    assert restored.qualities[0].is_audio


def test_format_selectors():
    selector = format_selector(720)
    assert "height<=720" in selector
    assert "avc1" in selector
    assert "height<=" not in format_selector(0)
    assert "ba" in audio_format_selector()


def test_quality_cache_key():
    media = MediaInfo(url="u", platform="youtube", media_id="abc", title="t")
    assert quality_cache_key(media, "720") == "youtube:abc:720"
    assert quality_cache_key(media, "audio") == "youtube:abc:audio"
