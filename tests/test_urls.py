from __future__ import annotations

import pytest

from bot.utils.urls import (
    detect_platform,
    extract_urls,
    host_of,
    is_direct_file,
    is_safe_public_url,
    normalize_url,
    sanitize_filename,
    youtube_id,
)


def test_extract_urls_with_scheme_and_tracking():
    urls = extract_urls("look https://youtu.be/abc123?si=tracking and that's it")
    assert urls == ["https://youtube.com/abc123"]


def test_extract_bare_domains_and_multiple():
    urls = extract_urls("check youtube.com/watch?v=xyz and https://x.com/user/status/1?utm_source=a")
    assert len(urls) == 2
    assert urls[0] == "https://youtube.com/watch?v=xyz"
    assert urls[1] == "https://x.com/user/status/1"


def test_extract_ignores_email_like_text():
    assert extract_urls("mail me at user@youtube.com") == []


def test_normalize_removes_utm_and_mobile_hosts():
    assert normalize_url("https://m.youtube.com/watch?v=abc&utm_source=x") == "https://youtube.com/watch?v=abc"
    assert normalize_url("www.instagram.com/reel/abc/") == "https://instagram.com/reel/abc/"
    assert normalize_url("https://youtu.be/abc") == "https://youtube.com/abc"


def test_detect_platforms():
    assert detect_platform("https://www.youtube.com/watch?v=x").code == "youtube"
    assert detect_platform("https://x.com/a/status/1").code == "twitter"
    assert detect_platform("https://vt.tiktok.com/abc").code == "tiktok"
    assert detect_platform("https://example.com/file.mp4").code == "direct"
    assert host_of("https://www.instagram.com/p/x") == "instagram.com"


def test_direct_files_and_youtube_id():
    assert is_direct_file("https://cdn.example.com/video.mp4?x=1")
    assert not is_direct_file("https://youtube.com/watch?v=1")
    assert youtube_id("https://youtu.be/dQw4w9WgXcQ?si=x") == "dQw4w9WgXcQ"
    assert youtube_id("https://youtube.com/shorts/abcdefghijk") == "abcdefghijk"
    assert youtube_id("https://example.com") is None


def test_sanitize_filename_blocks_traversal():
    assert "/" not in sanitize_filename("../../etc/passwd")
    assert sanitize_filename("") == "TELRO_download"
    assert len(sanitize_filename("x" * 500)) <= 120


@pytest.mark.asyncio
async def test_ssrf_guard_rejects_private_targets():
    assert not await is_safe_public_url("http://127.0.0.1/admin")
    assert not await is_safe_public_url("http://localhost:8080/")
    assert not await is_safe_public_url("ftp://example.com/file")
    assert not await is_safe_public_url("http://[::1]/")
