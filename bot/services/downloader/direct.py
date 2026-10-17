"""Direct HTTP(S) file downloader with SSRF protection and progress."""

from __future__ import annotations

import contextlib
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

import aiohttp
from yarl import URL

from bot.config import Settings
from bot.services.downloader.errors import DownloadCancelled, DownloadError, TooLargeError, UnsupportedError
from bot.utils.urls import is_safe_public_url, sanitize_filename

log = logging.getLogger(__name__)

_CHUNK = 256 * 1024
_CONTENT_RANGE_RE = re.compile(r"bytes\s+\d+-\d+/(\d+|\*)", re.IGNORECASE)
_FILENAME_STAR_RE = re.compile(r"filename\*\s*=\s*(?:UTF-8'')?([^;]+)", re.IGNORECASE)
_FILENAME_RE = re.compile(r'filename\s*=\s*"?([^";]+)"?', re.IGNORECASE)


@dataclass(slots=True)
class DirectFile:
    url: str
    filename: str
    size: int | None
    content_type: str
    kind: str  # video | audio | image | document

    @property
    def is_media(self) -> bool:
        return self.kind in {"video", "audio", "image"}


def _kind_from_content_type(content_type: str, filename: str) -> str:
    content_type = content_type.lower()
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("audio/"):
        return "audio"
    if content_type.startswith("image/"):
        return "image"
    suffix = Path(filename).suffix.lower()
    if suffix in {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".ts"}:
        return "video"
    if suffix in {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus"}:
        return "audio"
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
        return "image"
    return "document"


def _filename_from_headers(headers: aiohttp.typedefs.LooseHeaders, url: str) -> str:
    disposition = headers.get("Content-Disposition") or ""
    match = _FILENAME_STAR_RE.search(disposition)
    if match:
        return sanitize_filename(unquote(match.group(1).strip().strip('"')))
    match = _FILENAME_RE.search(disposition)
    if match:
        return sanitize_filename(unquote(match.group(1).strip()))
    path_name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    return sanitize_filename(path_name or "TELRO_download")


def _total_from_headers(headers: aiohttp.typedefs.LooseHeaders) -> int | None:
    content_range = headers.get("Content-Range") or ""
    match = _CONTENT_RANGE_RE.search(content_range)
    if match and match.group(1) != "*":
        return int(match.group(1))
    length = headers.get("Content-Length")
    if length and length.isdigit():
        return int(length)
    return None


class DirectDownloader:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg

    async def _request(
        self, session: aiohttp.ClientSession, url: str, *, method: str = "GET", headers: dict[str, str] | None = None
    ) -> tuple[aiohttp.ClientResponse, str]:
        current = url
        for _ in range(4):
            if not await is_safe_public_url(current):
                raise DownloadError("errors.unsafe_url", current)
            response = await session.request(method, current, headers=headers, allow_redirects=False)
            if response.status in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                response.release()
                if not location:
                    break
                current = URL(current).join(URL(location)).human_repr()
                continue
            return response, current
        raise DownloadError("errors.network", "too many redirects")

    async def probe(self, url: str) -> DirectFile:
        timeout = aiohttp.ClientTimeout(total=30, sock_read=20)
        headers = {"Range": "bytes=0-0", "User-Agent": "Mozilla/5.0 (compatible; TELRO/1.0)"}
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                response, final_url = await self._request(session, url)
                try:
                    if response.status in {401, 403}:
                        raise DownloadError("errors.forbidden")
                    if response.status in {404, 410}:
                        raise DownloadError("errors.unavailable")
                    if response.status >= 400 and response.status != 416:
                        response.release()
                        response, final_url = await self._request(session, url, method="HEAD")
                    content_type = (response.headers.get("Content-Type") or "application/octet-stream").split(";")[0]
                    size = _total_from_headers(response.headers)
                    if response.status == 416:
                        size = _total_from_headers(response.headers)
                    filename = _filename_from_headers(response.headers, final_url)
                    if content_type == "text/html":
                        raise UnsupportedError("errors.not_a_file")
                    kind = _kind_from_content_type(content_type, filename)
                    if not Path(filename).suffix:
                        suffix = {
                            "video": ".mp4",
                            "audio": ".mp3",
                            "image": ".jpg",
                            "document": "",
                        }[kind]
                        filename = sanitize_filename(filename + suffix)
                    if size and size > self.cfg.upload_limit:
                        raise TooLargeError("errors.too_large", str(size))
                    return DirectFile(
                        url=final_url,
                        filename=filename,
                        size=size,
                        content_type=content_type,
                        kind=kind,
                    )
                finally:
                    response.release()
        except (TimeoutError, aiohttp.ClientError) as exc:
            raise DownloadError("errors.network", str(exc)) from exc

    async def download(
        self,
        file: DirectFile,
        destination: Path,
        *,
        on_progress: Callable[[int, int | None, float], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        max_size: int | None = None,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        timeout = aiohttp.ClientTimeout(total=self.cfg.download_timeout, sock_read=60)
        limit = max_size or self.cfg.upload_limit
        downloaded = 0
        started = time.monotonic()
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                response, final_url = await self._request(
                    session, file.url, headers={"User-Agent": "Mozilla/5.0 (compatible; TELRO/1.0)"}
                )
                async with response:
                    if response.status >= 400:
                        raise DownloadError("errors.unavailable", f"HTTP {response.status}")
                    total = _total_from_headers(response.headers) or file.size
                    if total and total > limit:
                        raise TooLargeError("errors.too_large", str(total))
                    with destination.open("wb") as handle:
                        async for chunk in response.content.iter_chunked(_CHUNK):
                            if is_cancelled and is_cancelled():
                                raise DownloadCancelled
                            if not chunk:
                                continue
                            downloaded += len(chunk)
                            if downloaded > limit:
                                raise TooLargeError("errors.too_large", str(downloaded))
                            handle.write(chunk)
                            if on_progress:
                                elapsed = max(0.001, time.monotonic() - started)
                                on_progress(downloaded, total, downloaded / elapsed)
        except (TimeoutError, aiohttp.ClientError) as exc:
            with contextlib.suppress(OSError):
                destination.unlink()
            raise DownloadError("errors.network", str(exc)) from exc
        except DownloadCancelled:
            with contextlib.suppress(OSError):
                destination.unlink()
            raise
        if not destination.exists() or destination.stat().st_size == 0:
            raise DownloadError("errors.unknown", "empty file")
        return destination
