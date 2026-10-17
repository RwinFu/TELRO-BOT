"""Upload downloaded media to Telegram and cache file ids."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import FSInputFile, InlineKeyboardMarkup, Message

from bot.constants import TG_CAPTION_LIMIT
from bot.db.repository import CachedFile
from bot.services.downloader.errors import DownloadError, TooLargeError
from bot.services.downloader.formats import MediaInfo
from bot.utils.formatting import human_bytes, human_duration, quality_label, truncate
from bot.utils.text import esc
from bot.utils.urls import sanitize_filename

log = logging.getLogger(__name__)

_VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi"}
_AUDIO_SUFFIXES = {".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".aac"}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def detect_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _VIDEO_SUFFIXES:
        return "video"
    if suffix in _AUDIO_SUFFIXES:
        return "audio"
    if suffix in _IMAGE_SUFFIXES:
        return "photo"
    return "document"


class MediaSender:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------ caption
    @staticmethod
    def build_caption(
        media: MediaInfo,
        quality: str,
        size: int | None,
        *,
        title_override: str | None = None,
        direct_name: str | None = None,
    ) -> str:
        title = truncate(title_override or media.title or direct_name or "Media", 120)
        parts = [f"🎬 <b>{esc(title)}</b>"]
        meta: list[str] = []
        if media.uploader:
            meta.append(f"👤 {esc(truncate(media.uploader, 40))}")
        if media.duration:
            meta.append(f"⏱ {human_duration(media.duration)}")
        if size:
            meta.append(f"📦 {human_bytes(size)}")
        if quality == "audio":
            meta.append("🎵 MP3")
        elif quality and quality not in {"best", "document", "file"}:
            meta.append(f"🎞 {quality_label(int(quality)) if quality.isdigit() else esc(quality)}")
        if meta:
            parts.append(" · ".join(meta))
        url = media.webpage_url or media.url
        if url.startswith("http"):
            parts.append(f'🔗 <a href="{esc(url)}">منبع</a>')
        caption = "\n".join(parts)
        return caption[:TG_CAPTION_LIMIT]

    # -------------------------------------------------------------------- send
    async def send_file(
        self,
        chat_id: int,
        path: Path,
        caption: str,
        *,
        media: MediaInfo | None = None,
        quality: str = "best",
        reply_markup: InlineKeyboardMarkup | None = None,
        as_document: bool = False,
    ) -> Message:
        if not path.exists():
            raise DownloadError("errors.unknown", "file missing before upload")
        size = path.stat().st_size
        filename = sanitize_filename(path.name)
        file = FSInputFile(path, filename=filename)
        kind = "document" if as_document else detect_kind(path)
        duration = int(media.duration) if media and media.duration else None
        width = None
        height = None
        thumb = media.thumbnail if media else None
        if media and quality.isdigit() and path.suffix.lower() in _VIDEO_SUFFIXES:
            height = int(quality)
        kwargs: dict[str, Any] = {
            "chat_id": chat_id,
            "caption": caption[:TG_CAPTION_LIMIT],
            "parse_mode": "HTML",
            "reply_markup": reply_markup,
        }
        if size > 10 * 1024 * 1024 and kind == "photo":
            kind = "document"

        attempts = 0
        while True:
            attempts += 1
            try:
                if kind == "video":
                    try:
                        return await self.bot.send_video(
                            video=file,
                            duration=duration,
                            width=width,
                            height=height,
                            supports_streaming=True,
                            thumbnail=thumb,
                            **kwargs,
                        )
                    except TelegramBadRequest as exc:
                        log.debug("send_video retry without extras: %s", exc)
                        return await self.bot.send_video(video=file, supports_streaming=True, **kwargs)
                if kind == "audio":
                    return await self.bot.send_audio(
                        audio=file,
                        title=truncate((media.title if media else path.stem), 64),
                        performer=truncate((media.uploader if media else "") or "TELRO", 64),
                        duration=duration,
                        thumbnail=thumb,
                        **kwargs,
                    )
                if kind == "photo":
                    return await self.bot.send_photo(photo=file, **kwargs)
                return await self.bot.send_document(document=file, **kwargs)
            except TelegramRetryAfter as exc:
                if attempts >= 4:
                    raise DownloadError("errors.network", "flood wait") from exc
                await asyncio.sleep(exc.retry_after + 1)
                attempts -= 1
            except TelegramBadRequest as exc:
                text = str(exc).lower()
                if "too large" in text or "file is too big" in text:
                    raise TooLargeError("errors.too_large", str(exc)) from exc
                if "thumbnail" in text or "dimensions" in text or "wrong file identifier" in text:
                    thumb = None
                    height = None
                    continue
                if attempts >= 3:
                    raise DownloadError("errors.upload", str(exc)) from exc
                await asyncio.sleep(1)
            except TelegramForbiddenError as exc:
                raise DownloadError("errors.blocked", str(exc)) from exc

    async def send_cached(
        self,
        chat_id: int,
        cached: CachedFile,
        caption: str,
        *,
        reply_markup: InlineKeyboardMarkup | None = None,
        media: MediaInfo | None = None,
        quality: str = "best",
    ) -> Message:
        file_id = cached.file_ids[0] if cached.file_ids else ""
        if not file_id:
            raise DownloadError("errors.unknown", "empty cache entry")
        kwargs: dict[str, Any] = {
            "chat_id": chat_id,
            "caption": caption[:TG_CAPTION_LIMIT],
            "parse_mode": "HTML",
            "reply_markup": reply_markup,
        }
        if cached.kind == "video":
            return await self.bot.send_video(
                video=file_id,
                duration=media.duration if media else None,
                thumbnail=media.thumbnail if media else None,
                supports_streaming=True,
                **kwargs,
            )
        if cached.kind == "audio":
            return await self.bot.send_audio(
                audio=file_id,
                title=truncate((media.title if media else cached.title) or "Audio", 64),
                performer=truncate((media.uploader if media else "") or "TELRO", 64),
                duration=media.duration if media else None,
                thumbnail=media.thumbnail if media else None,
                **kwargs,
            )
        if cached.kind == "photo":
            return await self.bot.send_photo(photo=file_id, **kwargs)
        return await self.bot.send_document(document=file_id, **kwargs)
