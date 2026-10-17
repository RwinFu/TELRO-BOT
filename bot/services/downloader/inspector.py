"""Metadata extraction (yt-dlp) and music search."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import aiohttp
import yt_dlp

from bot.config import Settings
from bot.constants import INSPECT_CACHE_TTL_SECONDS
from bot.services.downloader.errors import DownloadError, UnsupportedError
from bot.services.downloader.formats import MediaInfo, build_qualities
from bot.utils.urls import detect_platform, is_spotify, normalize_url, spotify_kind

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    duration: int
    uploader: str
    thumbnail: str | None
    video_id: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "duration": self.duration,
            "uploader": self.uploader,
            "thumbnail": self.thumbnail,
            "video_id": self.video_id,
        }

    @classmethod
    def from_payload(cls, item: dict[str, Any]) -> SearchResult:
        return cls(
            title=str(item.get("title") or ""),
            url=str(item.get("url") or ""),
            duration=int(item.get("duration") or 0),
            uploader=str(item.get("uploader") or ""),
            thumbnail=item.get("thumbnail"),
            video_id=str(item.get("video_id") or ""),
        )


def _best_thumbnail(info: dict[str, Any]) -> str | None:
    thumbnails = info.get("thumbnails") or []
    candidates = [t for t in thumbnails if isinstance(t, dict) and t.get("url")]
    if candidates:
        candidates.sort(key=lambda t: (t.get("preference") or 0, t.get("width") or 0), reverse=True)
        return str(candidates[0]["url"])
    value = info.get("thumbnail")
    return str(value) if value else None


def _entry_url(entry: dict[str, Any]) -> str | None:
    for key in ("webpage_url", "url"):
        value = entry.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    video_id = entry.get("id")
    ie_key = str(entry.get("ie_key") or "").lower()
    if video_id and "youtube" in ie_key:
        return f"https://www.youtube.com/watch?v={video_id}"
    return None


def media_info_from_ytdlp(info: dict[str, Any], source_url: str) -> MediaInfo:
    platform = detect_platform(source_url).code
    if info.get("_type") == "playlist" or info.get("entries"):
        entries = [entry for entry in (info.get("entries") or []) if isinstance(entry, dict)]
        urls = [url for entry in entries if (url := _entry_url(entry))]
        count = info.get("playlist_count") or len(urls)
        return MediaInfo(
            url=source_url,
            platform=platform,
            media_id=str(info.get("id") or ""),
            title=str(info.get("title") or "Playlist"),
            uploader=str(info.get("uploader") or info.get("channel") or ""),
            duration=0,
            view_count=None,
            thumbnail=_best_thumbnail(info),
            webpage_url=str(info.get("webpage_url") or source_url),
            qualities=[],
            is_playlist=True,
            entry_count=int(count or 0),
            entries=urls[:25],
        )

    qualities, audio_size = build_qualities(info)
    duration = int(info.get("duration") or 0)
    is_audio_only = not any(not option.is_audio for option in qualities)
    return MediaInfo(
        url=source_url,
        platform=platform,
        media_id=str(info.get("id") or ""),
        title=str(info.get("title") or info.get("fulltitle") or "Media"),
        uploader=str(info.get("uploader") or info.get("channel") or info.get("creator") or ""),
        duration=duration,
        view_count=info.get("view_count"),
        thumbnail=_best_thumbnail(info),
        webpage_url=str(info.get("webpage_url") or source_url),
        qualities=qualities,
        audio_size=audio_size,
        is_live=bool(info.get("is_live")),
        is_audio_only=is_audio_only,
    )


def _is_playlist_url(url: str) -> bool:
    parts = urlsplit(url)
    path = parts.path.lower()
    if is_spotify(url):
        return False
    if "/playlist" in path or "/album/" in path or "/sets/" in path or "/show/" in path:
        return True
    if "soundcloud.com" in (parts.hostname or "") and "/sets/" in path:
        return True
    return False


class Inspector:
    """Extracts metadata with yt-dlp and caches the result in memory."""

    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self._cache: OrderedDict[str, tuple[float, MediaInfo]] = OrderedDict()
        self._cache_max = 128

    # ------------------------------------------------------------------ yt-dlp
    def base_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "skip_download": True,
            "socket_timeout": 25,
            "retries": 2,
            "extractor_retries": 2,
            "http_headers": {
                "User-Agent": USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
            },
            "cachedir": str(self.cfg.data_dir / "yt-dlp-cache"),
            "geo_bypass": True,
        }
        if self.cfg.proxy:
            options["proxy"] = self.cfg.proxy
        if self.cfg.cookies_file and Path(self.cfg.cookies_file).is_file():
            options["cookiefile"] = self.cfg.cookies_file
        return options

    def _extract_sync(self, url: str, *, playlist: bool, flat: bool = False) -> dict[str, Any]:
        target = url
        if not url.startswith(("http://", "https://")) and not url.startswith("ytsearch"):
            target = normalize_url(url)
        options = self.base_options()
        options["noplaylist"] = not playlist
        if flat:
            options["extract_flat"] = "in_playlist"
            options["playlistend"] = 25
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(target, download=False)
            if info is None:
                raise DownloadError("errors.unsupported", "empty response")
            return ydl.sanitize_info(info)

    async def _extract(self, url: str, *, playlist: bool | None = None, flat: bool = False) -> dict[str, Any]:
        if playlist is None:
            playlist = _is_playlist_url(url)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._extract_sync, url, playlist=playlist, flat=flat),
                timeout=self.cfg.extract_timeout,
            )
        except TimeoutError as exc:
            raise DownloadError("errors.timeout", "metadata timeout") from exc
        except DownloadError:
            raise
        except Exception as exc:  # yt-dlp raises a huge variety of errors
            from bot.services.downloader.errors import classify_error

            raise classify_error(exc) from exc

    # ------------------------------------------------------------------ Spotify
    async def _spotify_search_query(self, url: str) -> str:
        kind = spotify_kind(url)
        if kind not in {"track", "episode"}:
            raise UnsupportedError("errors.spotify_playlist", f"spotify kind={kind}")
        endpoint = f"https://open.spotify.com/oembed?url={quote(url, safe='')}"
        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(endpoint, headers={"User-Agent": USER_AGENT}) as response:
                    if response.status != 200:
                        raise UnsupportedError("errors.spotify", f"oembed status={response.status}")
                    data = await response.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise DownloadError("errors.network", str(exc)) from exc
        title = str(data.get("title") or "").strip()
        author = str(data.get("author_name") or "").strip()
        if not title:
            raise UnsupportedError("errors.spotify")
        return f"{title} {author}".strip()

    async def _resolve_spotify(self, url: str) -> str:
        query = await self._spotify_search_query(url)
        try:
            info = await self._extract(f"ytsearch1:{query}", playlist=True, flat=True)
        except DownloadError as exc:
            raise DownloadError("errors.spotify", exc.detail) from exc
        entries = [entry for entry in (info.get("entries") or []) if isinstance(entry, dict)]
        if not entries:
            raise UnsupportedError("errors.spotify")
        target = _entry_url(entries[0])
        if not target:
            raise UnsupportedError("errors.spotify")
        return target

    # ------------------------------------------------------------------- public
    async def inspect(self, url: str, *, use_cache: bool = True) -> MediaInfo:
        original = url
        if is_spotify(url):
            url = await self._resolve_spotify(url)
        key = url.lower()
        if use_cache:
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic():
                self._cache.move_to_end(key)
                return cached[1]

        info = await self._extract(url, playlist=None if not is_spotify(original) else False)
        media = media_info_from_ytdlp(info, original)
        if is_spotify(original):
            media.download_url = url
            media.platform = "spotify"
            media.url = original
            media.webpage_url = original
        self._cache[key] = (time.monotonic() + INSPECT_CACHE_TTL_SECONDS, media)
        while len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)
        return media

    def peek(self, url: str) -> MediaInfo | None:
        cached = self._cache.get(url.lower())
        if cached and cached[0] > time.monotonic():
            return cached[1]
        return None

    # -------------------------------------------------------------------- search
    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        query = query.strip()
        if not query:
            return []
        target = f"ytsearch{max(limit * 2, 8)}:{query}"
        info = await self._extract(target, playlist=True, flat=True)
        results: list[SearchResult] = []
        seen: set[str] = set()
        for entry in info.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            url = _entry_url(entry)
            if not url or url in seen:
                continue
            duration = int(entry.get("duration") or 0)
            if duration and duration > 4 * 3600:
                continue
            seen.add(url)
            results.append(
                SearchResult(
                    title=str(entry.get("title") or "Unknown"),
                    url=url,
                    duration=duration,
                    uploader=str(entry.get("uploader") or entry.get("channel") or ""),
                    thumbnail=_best_thumbnail(entry),
                    video_id=str(entry.get("id") or ""),
                )
            )
            if len(results) >= limit:
                break
        return results
