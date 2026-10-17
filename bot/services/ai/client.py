"""OpenAI-compatible streaming client used for chat and vision."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

import aiohttp

from bot.config import Settings
from bot.services.downloader.errors import AIError

log = logging.getLogger(__name__)


class AIClient:
    """Talks to any OpenAI-compatible ``/chat/completions`` endpoint.

    Works with OpenAI, OpenRouter, Groq, DeepSeek, Gemini's compatibility API,
    a local Ollama/LM Studio server and the free Pollinations endpoint.
    """

    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self._session: aiohttp.ClientSession | None = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.cfg.ai_timeout, sock_read=self.cfg.ai_timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    @property
    def endpoint(self) -> str:
        base = (self.cfg.ai_base_url or "").strip().rstrip("/")
        if not base:
            raise AIError("ai.not_configured")
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return base + "/chat/completions"
        return base + "/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
            "User-Agent": "TELRO-Bot/1.0",
            "HTTP-Referer": f"https://t.me/{self.cfg.bot_username}",
            "X-Title": "TELRO",
        }
        key = self.cfg.ai_api_key.get_secret_value().strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def stream(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        stream: bool | None = None,
    ) -> AsyncIterator[str]:
        payload = {
            "model": model or self.cfg.ai_model,
            "messages": list(messages),
            "stream": self.cfg.ai_stream if stream is None else stream,
            "max_tokens": max_tokens or self.cfg.ai_max_tokens,
            "temperature": temperature,
        }
        url = self.endpoint
        if "pollinations" in url:
            payload["referrer"] = "telro-bot"
        try:
            async with self.session.post(url, json=payload, headers=self._headers()) as response:
                if response.status != 200:
                    body = (await response.text())[:500]
                    raise self._error_for_status(response.status, body)
                content_type = response.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    data = await response.json(content_type=None)
                    text = extract_content(data)
                    if text:
                        yield text
                    return
                async for text in _iter_sse(response):
                    yield text
        except aiohttp.ClientError as exc:
            raise AIError("ai.unavailable", str(exc)) from exc
        except TimeoutError as exc:
            raise AIError("ai.timeout", "request timed out") from exc

    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> str:
        parts: list[str] = []
        async for chunk in self.stream(
            messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False,
        ):
            parts.append(chunk)
        return "".join(parts).strip()

    async def transcribe(self, audio: bytes, filename: str = "voice.ogg") -> str:
        if not self.cfg.ai_transcribe:
            raise AIError("ai.transcribe_disabled")
        base = self.cfg.ai_base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        url = base + "/audio/transcriptions"
        form = aiohttp.FormData()
        form.add_field("file", audio, filename=filename, content_type="audio/ogg")
        form.add_field("model", "whisper-1")
        headers = {"Authorization": f"Bearer {self.cfg.ai_api_key.get_secret_value()}"}
        try:
            async with self.session.post(url, data=form, headers=headers) as response:
                if response.status != 200:
                    raise self._error_for_status(response.status, (await response.text())[:300])
                data = await response.json(content_type=None)
                return str(data.get("text") or "").strip()
        except aiohttp.ClientError as exc:
            raise AIError("ai.unavailable", str(exc)) from exc

    @staticmethod
    def _error_for_status(status: int, body: str) -> AIError:
        detail = f"HTTP {status}: {body}"[:500]
        if status in {401, 403}:
            return AIError("ai.auth", detail)
        if status == 402:
            return AIError("ai.quota", detail)
        if status == 429:
            return AIError("ai.rate_limit", detail)
        if status == 404:
            return AIError("ai.model", detail)
        if status >= 500:
            return AIError("ai.unavailable", detail)
        return AIError("ai.error", detail)


async def _iter_sse(response: aiohttp.ClientResponse) -> AsyncIterator[str]:
    """Parse Server-Sent Events and yield text deltas."""
    while True:
        line = await response.content.readline()
        if not line:
            break
        decoded = line.decode("utf-8", "ignore").strip()
        if not decoded or decoded.startswith(":"):
            continue
        if decoded.startswith("data:"):
            decoded = decoded[5:].strip()
        if not decoded or decoded == "[DONE]":
            if decoded == "[DONE]":
                break
            continue
        try:
            data = json.loads(decoded)
        except json.JSONDecodeError:
            # Some gateways stream plain text instead of JSON chunks.
            yield decoded
            continue
        if isinstance(data, dict) and data.get("error"):
            message = data["error"]
            if isinstance(message, dict):
                message = message.get("message") or str(message)
            raise AIError("ai.error", str(message)[:300])
        text = extract_content(data)
        if text:
            yield text


def extract_content(data: dict[str, Any]) -> str:
    """Pull assistant text out of an OpenAI-style response object."""
    choices = data.get("choices") or []
    if not choices:
        return ""
    choice = choices[0] or {}
    for key in ("delta", "message"):
        value = choice.get(key)
        if isinstance(value, dict):
            content = value.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        parts.append(item["text"])
                return "".join(parts)
    text = choice.get("text")
    return text if isinstance(text, str) else ""


def build_user_content(prompt: str, image_data_url: str | None = None) -> str | list[dict[str, Any]]:
    if not image_data_url:
        return prompt
    return [
        {"type": "text", "text": prompt or "این تصویر را توضیح بده."},
        {"type": "image_url", "image_url": {"url": image_data_url}},
    ]


def build_messages(
    system_prompt: str,
    history: Sequence[tuple[str, str]],
    user_content: str | list[dict[str, Any]],
    *,
    max_chars: int = 12000,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    trimmed: list[dict[str, Any]] = []
    total = 0
    for role, content in reversed(history):
        if role not in {"user", "assistant"}:
            continue
        if total + len(content) > max_chars:
            break
        total += len(content)
        trimmed.append({"role": role, "content": content})
    messages.extend(reversed(trimmed))
    messages.append({"role": "user", "content": user_content})
    return messages
