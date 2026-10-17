"""Download orchestration: queueing, progress cards, caching and delivery."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.constants import PROGRESS_INTERVAL
from bot.db.repository import Repository, User
from bot.i18n import i18n
from bot.services.downloader.direct import DirectDownloader, DirectFile
from bot.services.downloader.engine import DownloadEngine, DownloadResult
from bot.services.downloader.errors import (
    DownloadCancelled,
    DownloadError,
    TooLargeError,
    classify_error,
)
from bot.services.downloader.formats import MediaInfo, quality_cache_key
from bot.services.downloader.inspector import Inspector
from bot.services.downloader.sender import MediaSender, detect_kind
from bot.utils.formatting import (
    human_bytes,
    human_eta,
    human_speed,
    progress_bar,
    truncate,
)
from bot.utils.telegram import safe_delete, safe_edit
from bot.utils.text import esc
from bot.utils.urls import sanitize_filename

log = logging.getLogger(__name__)

_SPINNER = ("⏳", "⌛️", "⏳", "⌛️")


@dataclass(slots=True)
class JobItem:
    url: str
    media: MediaInfo | None = None
    quality: str = "best"


@dataclass
class DownloadJob:
    id: str
    user_id: int
    chat_id: int
    lang: str
    platform: str
    quality: str
    title: str = ""
    token: str = ""
    items: list[JobItem] = field(default_factory=list)
    direct: DirectFile | None = None
    audio_format: str = "mp3"
    audio_bitrate: int = 192
    message: Message | None = None
    status: str = "queued"
    downloaded: int = 0
    total: int = 0
    speed: float = 0
    eta: int = 0
    percent: float = 0
    index: int = 0
    total_items: int = 1
    cached_hits: int = 0
    sent: int = 0
    bytes_sent: int = 0
    failed: int = 0
    cancelled: bool = False
    finished: bool = False
    card_alive: bool = True
    error_key: str = ""
    error_detail: str = ""
    ytdlp_log: list[str] = field(default_factory=list)
    download_id: int = 0
    started_at: float = 0.0
    created_at: float = field(default_factory=time.monotonic)
    last_text: str = ""
    compress_height: int = 0
    sent_messages: list[Message] = field(default_factory=list)
    task: asyncio.Task[Any] | None = None

    @property
    def percent_value(self) -> float:
        if self.total > 0:
            return max(0.0, min(100.0, self.downloaded / self.total * 100))
        return max(0.0, min(100.0, self.percent))

    def append_log(self, message: str) -> None:
        self.ytdlp_log.append(message[:500])
        if len(self.ytdlp_log) > 40:
            del self.ytdlp_log[: len(self.ytdlp_log) - 40]

    def progress_hook(self, data: dict[str, Any]) -> None:
        if self.cancelled:
            raise DownloadCancelled
        status = data.get("status")
        if status == "downloading":
            self.status = "downloading"
            self.downloaded = int(data.get("downloaded_bytes") or 0)
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            if total:
                self.total = int(total)
            self.speed = float(data.get("speed") or 0)
            self.eta = int(data.get("eta") or 0)
            self.percent = self.downloaded / self.total * 100 if self.total else 0
        elif status == "finished":
            self.status = "processing"
            if self.total:
                self.downloaded = self.total

    def postprocessor_hook(self, data: dict[str, Any]) -> None:
        if self.cancelled:
            raise DownloadCancelled
        if data.get("status") in {"started", "processing"}:
            self.status = "processing"

    def update_progress(self, downloaded: int, total: int | None, speed: float) -> None:
        if self.cancelled:
            raise DownloadCancelled
        self.status = "downloading"
        self.downloaded = downloaded
        if total:
            self.total = total
        self.speed = speed
        elapsed = downloaded / speed if speed > 0 else 0
        if total and speed > 0:
            self.eta = int(max(0, (total - downloaded) / speed))
        self.percent = self.downloaded / self.total * 100 if self.total else 0
        del elapsed


class DownloadManager:
    def __init__(
        self,
        cfg: Settings,
        repo: Repository,
        bot: Bot,
        inspector: Inspector,
        engine: DownloadEngine,
        direct: DirectDownloader,
        sender: MediaSender,
    ) -> None:
        self.cfg = cfg
        self.repo = repo
        self.bot = bot
        self.inspector = inspector
        self.engine = engine
        self.direct = direct
        self.sender = sender
        self._semaphore = asyncio.Semaphore(max(1, cfg.max_concurrent_downloads))
        self._user_locks: dict[int, asyncio.Lock] = {}
        self._jobs: dict[str, DownloadJob] = {}
        self._tasks: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------------ helpers
    @property
    def active_count(self) -> int:
        return sum(1 for job in self._jobs.values() if not job.finished)

    def active_for_user(self, user_id: int) -> bool:
        return any(job.user_id == user_id and not job.finished for job in self._jobs.values())

    def create_job(
        self,
        user: User,
        message: Message,
        *,
        platform: str,
        quality: str,
        media: MediaInfo | None = None,
        direct_file: DirectFile | None = None,
        token: str = "",
        title: str = "",
        items: list[JobItem] | None = None,
    ) -> DownloadJob:
        job = DownloadJob(
            id=secrets.token_hex(4),
            user_id=user.id,
            chat_id=message.chat.id,
            lang=user.language,
            platform=platform,
            quality=quality,
            title=title or (media.title if media else (direct_file.filename if direct_file else "")),
            token=token,
            audio_format=user.pref_audio or "mp3",
            audio_bitrate=192,
            message=message,
            direct=direct_file,
        )
        if items:
            job.items = items
        elif media is not None:
            job.items = [JobItem(url=media.url, media=media, quality=quality)]
        elif direct_file is not None:
            job.items = []
        job.total_items = max(1, len(job.items))
        return job

    # --------------------------------------------------------------------- start
    def start(self, job: DownloadJob) -> asyncio.Task[Any]:
        self._jobs[job.id] = job
        task = asyncio.create_task(self._run(job), name=f"download-{job.id}")
        job.task = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def cancel(self, user_id: int, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.user_id != user_id or job.finished:
            return False
        job.cancelled = True
        if job.status == "queued" and job.task:
            job.task.cancel()
        return True

    async def shutdown(self) -> None:
        for job in list(self._jobs.values()):
            job.cancelled = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ------------------------------------------------------------------- execute
    async def _run(self, job: DownloadJob) -> None:
        ui = asyncio.create_task(self._ui_loop(job))
        acquired_user = False
        acquired_global = False
        error: BaseException | None = None
        try:
            lock = self._user_locks.setdefault(job.user_id, asyncio.Lock())
            if lock.locked():
                job.status = "queued"
            await lock.acquire()
            acquired_user = True

            if job.cancelled:
                raise DownloadCancelled
            if self._semaphore.locked():
                job.status = "queued"
            await self._semaphore.acquire()
            acquired_global = True
            if job.cancelled:
                raise DownloadCancelled

            job.started_at = time.monotonic()
            first = job.items[0] if job.items else None
            platform = job.platform
            title = job.title or (first.media.title if first and first.media else "")
            job.download_id = await self.repo.log_download(
                job.user_id,
                first.url if first else (job.direct.url if job.direct else ""),
                platform,
                title,
                job.quality,
            )
            job.status = "starting"

            if job.direct is not None:
                await self._run_direct(job)
            else:
                await self._run_items(job)
            job.status = "done"
        except DownloadCancelled:
            job.status = "cancelled"
            job.error_key = "download.cancelled"
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.error_key = "download.cancelled"
            job.cancelled = True
        except DownloadError as exc:
            job.status = "failed"
            job.error_key = exc.key
            job.error_detail = exc.detail
            error = exc
        except Exception as exc:  # pragma: no cover - unexpected
            log.exception("Unhandled download error for job %s", job.id)
            job.status = "failed"
            classified = classify_error(exc)
            job.error_key = classified.key
            job.error_detail = classified.detail
            error = exc
        finally:
            job.finished = True
            ui.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ui
            if acquired_global:
                self._semaphore.release()
            if acquired_user:
                lock = self._user_locks.get(job.user_id)
                if lock and lock.locked():
                    lock.release()
            await self._finalize(job, error)
            self._cleanup_files(job)
            self._jobs.pop(job.id, None)

    async def _run_items(self, job: DownloadJob) -> None:
        first_error: DownloadError | None = None
        for index, item in enumerate(job.items, start=1):
            if job.cancelled:
                raise DownloadCancelled
            job.index = index
            job.total_items = len(job.items)
            job.downloaded = 0
            job.total = 0
            job.percent = 0
            media: MediaInfo
            try:
                media = item.media or await self.inspector.inspect(item.url)
                item.media = media
                if not job.title:
                    job.title = media.title
                if media.is_playlist:
                    raise DownloadError("errors.playlist_inside", media.title)
                cache_key = self._cache_key(media, item.quality, job)
                cached = await self.repo.cache_get(cache_key)
                if cached:
                    job.status = "cached"
                    try:
                        caption = self._caption(job, media, cached.size)
                        await self.sender.send_cached(
                            job.chat_id,
                            cached,
                            caption,
                            reply_markup=self._media_keyboard(job, media, item.quality),
                            media=media,
                            quality=item.quality,
                        )
                        job.cached_hits += 1
                        job.sent += 1
                        await self.repo.bump_counter("cache_hits")
                        continue
                    except Exception as exc:  # stale file_id, revoked file, etc.
                        log.warning("cache send failed (%s), redownloading", exc)
                        await self.repo.cache_delete(cache_key)
                await self.repo.bump_counter("cache_misses")

                result = await self._download_media(job, media, item.quality)
                await self._deliver(job, media, item.quality, result)
                job.sent += 1
            except DownloadCancelled:
                raise
            except DownloadError as exc:
                job.failed += 1
                first_error = first_error or exc
                log.warning("download item failed %s: %s (%s)", item.url, exc.key, exc.detail)
                continue
        if job.sent == 0 and first_error is not None:
            raise first_error

    async def _download_media(self, job: DownloadJob, media: MediaInfo, quality: str) -> DownloadResult:
        temp_dir = self.cfg.download_dir / job.id / str(job.index)
        temp_dir.mkdir(parents=True, exist_ok=True)
        quality = quality or "best"
        job.status = "downloading"
        job.total = 0
        job.downloaded = 0
        return await self.engine.download(
            media,
            quality,
            temp_dir,
            job,
            audio_format=job.audio_format if quality == "audio" else "mp3",
            audio_bitrate=job.audio_bitrate,
        )

    async def _run_direct(self, job: DownloadJob) -> None:
        assert job.direct is not None
        file = job.direct
        temp_dir = self.cfg.download_dir / job.id
        temp_dir.mkdir(parents=True, exist_ok=True)
        job.status = "downloading"
        job.total = file.size or 0
        target = temp_dir / sanitize_filename(file.filename)
        await self.direct.download(
            file,
            target,
            on_progress=job.update_progress,
            is_cancelled=lambda: job.cancelled,
        )
        if job.cancelled:
            raise DownloadCancelled

        if job.quality == "audio" and file.kind == "video":
            job.status = "processing"
            audio = await self.engine.extract_audio(target, temp_dir, bitrate=job.audio_bitrate)
            if audio is None:
                raise DownloadError("errors.ffmpeg")
            with contextlib.suppress(OSError):
                target.unlink()
            target = audio

        media = MediaInfo(
            url=file.url,
            platform="direct",
            media_id=hashlib.sha1(file.url.encode()).hexdigest()[:16],
            title=file.filename,
            webpage_url=file.url,
            qualities=[],
        )
        duplicate = self._duplicate_result(job, target, media, job.quality)
        await self._deliver(job, media, job.quality, duplicate)
        job.sent += 1

    def _duplicate_result(self, job: DownloadJob, path: Path, media: MediaInfo, quality: str) -> DownloadResult:
        duration = 0
        return DownloadResult(
            paths=[path],
            info={"title": media.title, "duration": duration},
            title=media.title,
            duration=duration,
            size=path.stat().st_size,
        )

    # ------------------------------------------------------------------ delivery
    async def _deliver(self, job: DownloadJob, media: MediaInfo, quality: str, result: DownloadResult) -> None:
        if not result.paths:
            raise DownloadError("errors.unknown", "empty result")
        path = result.paths[0]
        size = path.stat().st_size
        limit = self.cfg.upload_limit
        kind = detect_kind(path)

        if size > limit:
            path, size, kind = await self._shrink(job, path, size, kind, limit)

        duration = result.duration or media.duration
        if job.quality == "audio" and path.suffix.lower() not in {".mp3", ".m4a"}:
            converted = await self.engine.extract_audio(path, path.parent, bitrate=job.audio_bitrate)
            if converted:
                with contextlib.suppress(OSError):
                    path.unlink()
                path = converted
                size = path.stat().st_size
                kind = "audio"
        if duration and not media.duration:
            media.duration = duration
        job.status = "uploading"
        caption = self._caption(job, media, size)
        message = await self.sender.send_file(
            job.chat_id,
            path,
            caption,
            media=media,
            quality=quality,
            reply_markup=self._media_keyboard(job, media, quality),
            as_document=self.cfg.send_as_document,
        )
        job.sent_messages.append(message)
        job.bytes_sent += size
        file_id = self._extract_file_id(message)
        if file_id:
            with contextlib.suppress(Exception):
                await self.repo.cache_put(
                    self._cache_key(media, quality, job),
                    kind,
                    [file_id],
                    title=media.title,
                    size=size,
                )
        with contextlib.suppress(OSError):
            path.unlink()

    async def _shrink(self, job: DownloadJob, path: Path, size: int, kind: str, limit: int) -> tuple[Path, int, str]:
        if kind == "video" and self.cfg.auto_compress and self.cfg.ffmpeg_available:
            job.status = "compressing"
            compressed = await self.engine.compress(
                path,
                limit,
                path.parent,
                on_status=lambda value: setattr(
                    job, "compress_height", int(value.split(":")[-1]) if ":" in value else 0
                ),
            )
            if compressed is None:
                raise TooLargeError("errors.too_large", str(size))
            with contextlib.suppress(OSError):
                if compressed != path:
                    path.unlink()
            return compressed, compressed.stat().st_size, detect_kind(compressed)
        if kind == "audio" and self.cfg.ffmpeg_available:
            for bitrate in (128, 96, 64, 48):
                job.status = "compressing"
                output = await self.engine.extract_audio(path, path.parent, bitrate=bitrate)
                if output and output.stat().st_size <= limit:
                    with contextlib.suppress(OSError):
                        path.unlink()
                    return output, output.stat().st_size, "audio"
            raise TooLargeError("errors.too_large", str(size))
        raise TooLargeError("errors.too_large", str(size))

    def _caption(self, job: DownloadJob, media: MediaInfo, size: int | None) -> str:
        caption = self.sender.build_caption(media, job.quality, size)
        if not caption:
            caption = f"🎬 <b>{esc(truncate(job.title or 'TELRO', 120))}</b>"
        if job.total_items > 1:
            caption = f"<i>{job.index}/{job.total_items}</i>\n" + caption
        return caption

    def _media_keyboard(self, job: DownloadJob, media: MediaInfo, quality: str) -> InlineKeyboardMarkup | None:
        if not job.token:
            return None
        rows: list[list[InlineKeyboardButton]] = []
        if quality != "audio" and not media.is_audio_only:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=i18n.get(job.lang, "buttons.get_audio"), callback_data=f"q:{job.token}:audio"
                    )
                ]
            )
        rows.append(
            [
                InlineKeyboardButton(
                    text=i18n.get(job.lang, "buttons.delete"), callback_data=f"delete:{job.user_id}"
                ),
                InlineKeyboardButton(text=i18n.get(job.lang, "buttons.source"), url=media.webpage_url or media.url)
                if (media.webpage_url or media.url).startswith("http")
                else InlineKeyboardButton(text=i18n.get(job.lang, "buttons.menu"), callback_data="menu:main"),
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @staticmethod
    def _extract_file_id(message: Message) -> str | None:
        for attribute in ("video", "audio", "photo", "document", "animation", "voice"):
            value = getattr(message, attribute, None)
            if value is None:
                continue
            if isinstance(value, list):
                if value:
                    return value[-1].file_id
                continue
            return value.file_id
        return None

    def _cache_key(self, media: MediaInfo, quality: str, job: DownloadJob) -> str:
        base = quality_cache_key(media, quality)
        if quality == "audio" or media.is_audio_only:
            return f"{base}:{job.audio_format}:{job.audio_bitrate}"
        return f"{base}:{job.audio_format}"

    # -------------------------------------------------------------------- render
    async def _ui_loop(self, job: DownloadJob) -> None:
        while not job.finished:
            with contextlib.suppress(Exception):
                await self._render(job)
            await asyncio.sleep(PROGRESS_INTERVAL)

    def _render_text(self, job: DownloadJob) -> str:
        lang = job.lang
        spin = _SPINNER[int(time.monotonic() * 2) % len(_SPINNER)]
        title = truncate(job.title or (job.direct.filename if job.direct else ""), 90)
        index = f" ({job.index}/{job.total_items})" if job.total_items > 1 else ""
        if job.status == "queued":
            body = i18n.get(lang, "download.queued")
        elif job.status == "starting":
            body = i18n.get(lang, "download.starting")
        elif job.status in {"downloading"}:
            if job.total:
                bar = progress_bar(job.percent_value)
                body = i18n.get(
                    lang,
                    "download.progress",
                    bar=bar,
                    percent=f"{job.percent_value:.0f}",
                    done=human_bytes(job.downloaded),
                    total=human_bytes(job.total),
                    speed=human_speed(job.speed),
                    eta=human_eta(job.eta),
                )
            else:
                body = i18n.get(
                    lang,
                    "download.progress_unknown",
                    done=human_bytes(job.downloaded),
                    speed=human_speed(job.speed),
                )
        elif job.status == "processing":
            body = i18n.get(lang, "download.processing")
        elif job.status == "compressing":
            body = i18n.get(lang, "download.compressing")
        elif job.status == "uploading":
            body = i18n.get(lang, "download.uploading")
        elif job.status == "cached":
            body = i18n.get(lang, "download.cached")
        elif job.status == "cancelled":
            body = i18n.get(lang, "download.cancelled")
        elif job.status == "failed":
            body = i18n.get(lang, "download.failed", error=i18n.get(lang, job.error_key or "errors.unknown"))
        else:
            body = i18n.get(lang, "download.processing")
        head = f"{spin} <b>{esc(i18n.get(lang, 'download.header'))}</b>{esc(index)}"
        title_line = f"\n\n🎬 <b>{esc(title)}</b>" if title else ""
        return f"{head}\n\n{body}{title_line}"

    def _render_keyboard(self, job: DownloadJob) -> InlineKeyboardMarkup | None:
        rows: list[list[InlineKeyboardButton]] = []
        if not job.finished and job.status != "cancelled":
            rows.append(
                [InlineKeyboardButton(text=i18n.get(job.lang, "buttons.cancel"), callback_data=f"cancel:{job.id}")]
            )
        elif job.status == "failed":
            row = []
            if job.token:
                retry_data = f"pl:{job.token}:first" if job.total_items > 1 else f"q:{job.token}:{job.quality}"
                row.append(
                    InlineKeyboardButton(
                        text=i18n.get(job.lang, "buttons.retry"),
                        callback_data=retry_data,
                    )
                )
            row.append(InlineKeyboardButton(text=i18n.get(job.lang, "buttons.menu"), callback_data="menu:main"))
            rows.append(row)
        return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None

    async def _render(self, job: DownloadJob) -> None:
        if not job.card_alive or job.message is None:
            return
        text = self._render_text(job)
        if text == job.last_text:
            return
        job.last_text = text
        ok = await safe_edit(job.message, text, self._render_keyboard(job))
        if not ok:
            job.card_alive = False

    async def _finalize(self, job: DownloadJob, error: BaseException | None) -> None:
        elapsed_ms = int((time.monotonic() - job.started_at) * 1000) if job.started_at else 0
        if job.download_id:
            status = "done" if job.status == "done" else ("cancelled" if job.status == "cancelled" else "failed")
            await self.repo.finish_download(
                job.download_id,
                status,
                size=job.bytes_sent or job.total or None,
                duration=0,
                elapsed_ms=elapsed_ms,
                error=job.error_detail or job.error_key or None,
            )
        if job.status in {"failed", "cancelled"} and job.sent == 0:
            with contextlib.suppress(Exception):
                await self.repo.refund_download(job.user_id)
            if job.card_alive and job.message is not None:
                job.finished = True
                await self._render(job)
                if job.status == "failed" and job.total_items > 1:
                    await self.bot.send_message(
                        job.chat_id,
                        i18n.get(job.lang, "download.batch_failed", failed=job.failed, total=job.total_items),
                    )
        elif job.status == "done" and job.sent:
            if job.card_alive and job.message is not None:
                await safe_delete(job.message)
                job.card_alive = False
            if job.failed:
                with contextlib.suppress(Exception):
                    await self.bot.send_message(
                        job.chat_id,
                        i18n.get(
                            job.lang,
                            "download.batch_partial",
                            sent=job.sent,
                            failed=job.failed,
                            total=job.total_items,
                        ),
                    )
            log.info(
                "job %s done user=%s platform=%s quality=%s items=%s cached=%s in %sms",
                job.id,
                job.user_id,
                job.platform,
                job.quality,
                job.sent,
                job.cached_hits,
                elapsed_ms,
            )
        elif job.status == "failed" and job.card_alive and job.message is not None:
            job.finished = True
            await self._render(job)
        if error and job.user_id in self.cfg.admins:
            log.debug("admin error trace job=%s: %r", job.id, error)
        job.last_text = ""

    def _cleanup_files(self, job: DownloadJob) -> None:
        directory = self.cfg.download_dir / job.id
        shutil.rmtree(directory, ignore_errors=True)

    async def cleanup_loop(self) -> None:
        """Periodically remove stale files and expired DB rows."""
        while True:
            try:
                await asyncio.sleep(1800)
                cutoff = time.time() - 6 * 3600
                for child in self.cfg.download_dir.iterdir():
                    try:
                        if child.stat().st_mtime < cutoff:
                            if child.is_dir():
                                shutil.rmtree(child, ignore_errors=True)
                            else:
                                child.unlink(missing_ok=True)
                    except OSError:
                        continue
                await self.repo.cleanup()
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - background safety net
                log.exception("cleanup loop error")
