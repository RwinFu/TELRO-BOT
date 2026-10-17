"""Image generation via Pollinations (free) or an OpenAI-compatible API."""

from __future__ import annotations

import asyncio
import base64
import logging
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import aiohttp

from bot.config import Settings
from bot.services.ai.prompts import BANNED_IMAGE_TERMS, IMAGE_PROMPT_SUFFIX
from bot.services.downloader.errors import ImageError

log = logging.getLogger(__name__)

ASPECTS: dict[str, tuple[int, int]] = {
    "square": (1024, 1024),
    "landscape": (1216, 832),
    "portrait": (832, 1216),
    "story": (768, 1344),
}
ASPECT_ALIASES = {
    "1:1": "square",
    "square": "square",
    "16:9": "landscape",
    "landscape": "landscape",
    "9:16": "portrait",
    "portrait": "portrait",
    "story": "story",
}


@dataclass(slots=True)
class GeneratedImage:
    path: Path
    prompt: str
    aspect: str
    provider: str
    seed: int


def build_pollinations_url(base: str, prompt: str, width: int, height: int, seed: int, model: str) -> str:
    base = base.rstrip("/")
    return (
        f"{base}/{quote(prompt, safe='')}"
        f"?width={width}&height={height}&seed={seed}&model={quote(model, safe='')}"
        "&nologo=true&enhance=true&private=true"
    )


def validate_prompt(prompt: str) -> str:
    prompt = " ".join((prompt or "").split()).strip()
    if len(prompt) < 3:
        raise ImageError("image.prompt_short")
    if len(prompt) > 900:
        prompt = prompt[:900]
    lowered = prompt.lower()
    if any(term in lowered for term in BANNED_IMAGE_TERMS):
        raise ImageError("image.banned")
    return prompt


def normalize_aspect(value: str | None) -> str:
    return ASPECT_ALIASES.get((value or "").lower().strip(), "square")


class ImageService:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self._session: aiohttp.ClientSession | None = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.cfg.image_timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def generate(self, prompt: str, aspect: str = "square") -> GeneratedImage:
        if not self.cfg.image_enabled:
            raise ImageError("image.disabled")
        prompt = validate_prompt(prompt)
        aspect = normalize_aspect(aspect)
        width, height = ASPECTS[aspect]
        seed = secrets.randbelow(2**31)
        provider = self.cfg.image_provider.lower().strip()
        if provider == "pollinations":
            data = await self._pollinations(prompt, width, height, seed)
        elif provider in {"openai", "dalle", "compatible"}:
            data = await self._openai(prompt, width, height)
        else:
            raise ImageError("image.disabled")
        self.cfg.generated_dir.mkdir(parents=True, exist_ok=True)
        path = self.cfg.generated_dir / f"telro_{int(time.time())}_{secrets.token_hex(3)}.jpg"
        path.write_bytes(data)
        return GeneratedImage(path=path, prompt=prompt, aspect=aspect, provider=provider, seed=seed)

    async def _pollinations(self, prompt: str, width: int, height: int, seed: int) -> bytes:
        url = build_pollinations_url(
            self.cfg.image_base_url, prompt, width, height, seed, self.cfg.image_model or "flux"
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with self.session.get(url, headers={"User-Agent": "TELRO-Bot/1.0"}) as response:
                    if response.status != 200:
                        body = (await response.text())[:200]
                        raise ImageError("image.error", f"HTTP {response.status}: {body}")
                    content_type = response.headers.get("Content-Type", "")
                    data = await response.read()
                    if not data or "image" not in content_type:
                        raise ImageError("image.error", f"unexpected content-type {content_type}")
                    if len(data) > 25 * 1024 * 1024:
                        raise ImageError("image.error", "image too large")
                    return data
            except (TimeoutError, aiohttp.ClientError) as exc:
                last_error = exc
                await asyncio.sleep(1.5 * (attempt + 1))
        raise ImageError("image.unavailable", str(last_error or "timeout"))

    async def _openai(self, prompt: str, width: int, height: int) -> bytes:
        key = self.cfg.image_api_key.get_secret_value().strip()
        if not key:
            raise ImageError("image.not_configured")
        payload = {
            "model": self.cfg.image_model or "gpt-image-1",
            "prompt": f"{prompt}, {IMAGE_PROMPT_SUFFIX}",
            "size": f"{width}x{height}" if width == height else "1024x1024",
            "n": 1,
            "response_format": "b64_json",
        }
        try:
            async with self.session.post(
                self.cfg.image_api_url,
                json=payload,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            ) as response:
                if response.status != 200:
                    raise ImageError("image.error", (await response.text())[:300])
                data = await response.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise ImageError("image.unavailable", str(exc)) from exc
        try:
            first = data["data"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ImageError("image.error", "invalid response") from exc
        if first.get("b64_json"):
            return base64.b64decode(first["b64_json"])
        if first.get("url"):
            async with self.session.get(first["url"]) as response:
                if response.status == 200:
                    return await response.read()
        raise ImageError("image.error", "no image in response")
