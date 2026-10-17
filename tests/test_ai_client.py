from __future__ import annotations

import json

import pytest

from bot.config import Settings
from bot.services.ai.client import (
    AIClient,
    _iter_sse,
    build_messages,
    build_user_content,
    extract_content,
)
from bot.services.downloader.errors import AIError


def test_extract_content_variants():
    assert extract_content({"choices": [{"delta": {"content": "hello"}}]}) == "hello"
    assert extract_content({"choices": [{"message": {"content": "done"}}]}) == "done"
    assert (
        extract_content(
            {"choices": [{"delta": {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}}]}
        )
        == "ab"
    )
    assert extract_content({"choices": [{"text": "legacy"}]}) == "legacy"
    assert extract_content({}) == ""


def test_build_messages_trims_history():
    history = [("user", "x" * 100), ("assistant", "y" * 100)] * 10
    messages = build_messages("system", history, "now", max_chars=450)
    assert messages[0] == {"role": "system", "content": "system"}
    assert messages[-1] == {"role": "user", "content": "now"}
    assert sum(len(item["content"]) for item in messages[1:-1]) <= 450


def test_build_user_content_with_image():
    plain = build_user_content("hi")
    assert plain == "hi"
    rich = build_user_content("what is this?", "data:image/jpeg;base64,abc")
    assert isinstance(rich, list)
    assert rich[0]["type"] == "text"
    assert rich[1]["image_url"]["url"].startswith("data:image/jpeg")


def test_error_mapping():
    assert AIClient._error_for_status(401, "").key == "ai.auth"
    assert AIClient._error_for_status(403, "").key == "ai.auth"
    assert AIClient._error_for_status(402, "").key == "ai.quota"
    assert AIClient._error_for_status(429, "").key == "ai.rate_limit"
    assert AIClient._error_for_status(404, "").key == "ai.model"
    assert AIClient._error_for_status(500, "").key == "ai.unavailable"
    assert AIClient._error_for_status(418, "").key == "ai.error"


def test_endpoint_building():
    cfg = Settings(_env_file=None, ai_base_url="https://api.openai.com/v1", bot_token="1:T")
    assert AIClient(cfg).endpoint == "https://api.openai.com/v1/chat/completions"
    cfg2 = Settings(_env_file=None, ai_base_url="https://example.com/chat/completions", bot_token="1:T")
    assert AIClient(cfg2).endpoint == "https://example.com/chat/completions"
    cfg3 = Settings(_env_file=None, ai_base_url="", bot_token="1:T")
    with pytest.raises(AIError):
        _ = AIClient(cfg3).endpoint


class _FakeContent:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = list(lines)

    async def readline(self) -> bytes:
        return self.lines.pop(0) if self.lines else b""


class _FakeResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self.content = _FakeContent(lines)


@pytest.mark.asyncio
async def test_sse_parsing():
    lines = [
        b"\n",
        b": ping\n",
        b'data: {"choices":[{"delta":{"content":"\xd8\xb3\xd9\x84\xd8\xa7\xd9\x85"}}]}\n',
        b'data: {"choices":[{"delta":{"content":"!"}}]}\n',
        b"data: [DONE]\n",
    ]
    chunks = [chunk async for chunk in _iter_sse(_FakeResponse(lines))]
    assert "".join(chunks) == "سلام!"


@pytest.mark.asyncio
async def test_sse_error_payload():
    lines = [b'data: {"error": {"message": "quota"}}\n']
    with pytest.raises(AIError):
        async for _ in _iter_sse(_FakeResponse(lines)):
            pass


def test_json_payload_streaming_line():
    content = json.dumps({"choices": [{"delta": {"content": "hi"}}]})
    assert content
