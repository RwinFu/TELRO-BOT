from __future__ import annotations

import pytest

from bot.services.ai.images import (
    ASPECTS,
    build_pollinations_url,
    normalize_aspect,
    validate_prompt,
)
from bot.services.downloader.errors import ImageError


def test_pollinations_url():
    url = build_pollinations_url(
        "https://image.pollinations.ai/prompt",
        "a cat on mars",
        1024,
        768,
        42,
        "flux",
    )
    assert url.startswith("https://image.pollinations.ai/prompt/a%20cat%20on%20mars?")
    assert "width=1024" in url
    assert "height=768" in url
    assert "seed=42" in url
    assert "nologo=true" in url


def test_validate_prompt():
    assert validate_prompt("  a   cat  ") == "a cat"
    with pytest.raises(ImageError):
        validate_prompt("ab")
    with pytest.raises(ImageError):
        validate_prompt("nude child")
    long_prompt = "x" * 2000
    assert len(validate_prompt(long_prompt)) == 900


def test_aspects():
    assert normalize_aspect("16:9") == "landscape"
    assert normalize_aspect("portrait") == "portrait"
    assert normalize_aspect("nonsense") == "square"
    assert ASPECTS["square"] == (1024, 1024)
