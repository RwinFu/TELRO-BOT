"""The actual yt-dlp download worker (runs in a thread)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yt_dlp

from bot.config import Settings
from bot.services.downloader.errors import DownloadCancelled, DownloadError, classify_error
from bot.services.downloader.formats import MediaInfo, audio_format_selector, format_selector

log = logging.getLogger(__name__)


@dataclass(slots=True)
class DownloadResult:
    paths: list[Path]
    info: dict[str, Any] = field(default_factory=dict)
    title: str = ""
    duration: int = 0
    width: int | None = None
    height: int | None = None
    size: int = 0


class _Logger:
    """Forward yt-dlp messages into the application log and job buffer."""

    def __init__(self, sink: Callable[[str], None] | None = None) -> None:
        self.sink = sink

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug]"):
            log.debug("yt-dlp: %s", msg)
            if self.sink:
                self.sink(msg)

    def info(self, msg: str) -> None:
        log.debug("yt-dlp: %s", msg)

    def warning(self, msg: str) -> None:
        log.warning("yt-dlp: %s", msg)
        if self.sink:
            self.sink(msg)

    def error(self, msg: str) -> None:
        log.error("yt-dlp: %s", msg)
        if self.sink:
            self.sink(msg)


class DownloadEngine:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg

    def _base_options(self, out_dir: Path, job: Any) -> dict[str, Any]:
        options: dict[str, Any] = {
            "paths": {"home": str(out_dir), "temp": str(out_dir)},
            "outtmpl": {"default": "%(title).120B [%(id)s].%(ext)s"},
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "concurrent_fragment_downloads": max(1, int(self.cfg.ytdlp_fragments)),
            "retries": 3,
            "fragment_retries": 5,
            "socket_timeout": 30,
            "overwrites": True,
            "continuedl": True,
            "windowsfilenames": False,
            "trim_file_name": 120,
            "logger": _Logger(job.append_log),
            "progress_hooks": [job.progress_hook],
            "postprocessor_hooks": [job.postprocessor_hook],
            "cachedir": str(self.cfg.data_dir / "yt-dlp-cache"),
            "http_headers": {"Accept-Language": "en-US,en;q=0.9,fa;q=0.8"},
            "progress_with_newline": False,
            "no_color": True,
        }
        if self.cfg.proxy:
            options["proxy"] = self.cfg.proxy
        if self.cfg.cookies_file and Path(self.cfg.cookies_file).is_file():
            options["cookiefile"] = self.cfg.cookies_file
        return options

    def download_sync(
        self,
        media: MediaInfo,
        quality: str,
        out_dir: Path,
        job: Any,
        *,
        audio_format: str = "mp3",
        audio_bitrate: int = 192,
    ) -> DownloadResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        target_url = media.target
        is_audio = quality == "audio" or media.is_audio_only
        options = self._base_options(out_dir, job)

        if is_audio:
            options["format"] = audio_format_selector() if self.cfg.ffmpeg_available else "ba/b"
            if self.cfg.ffmpeg_available:
                options["postprocessors"] = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": audio_format,
                        "preferredquality": str(audio_bitrate),
                    },
                    {"key": "FFmpegMetadata", "add_metadata": True},
                ]
        else:
            height = 0
            if quality not in {"best", "document", ""}:
                with contextlib.suppress(ValueError):
                    height = int(quality)
            if self.cfg.ffmpeg_available:
                options["format"] = format_selector(height, "document" if quality == "document" else "video")
                options["merge_output_format"] = "mp4"
            else:
                suffix = f"[height<={height}]" if height else ""
                options["format"] = f"b{suffix}[ext=mp4]/b{suffix}/b"

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(target_url, download=True)
                if info is None:
                    raise DownloadError("errors.unavailable", "yt-dlp returned no info")
                info = ydl.sanitize_info(info)
                if info.get("_type") == "playlist":
                    entries = [entry for entry in info.get("entries") or [] if entry]
                    if not entries:
                        raise DownloadError("errors.unavailable")
                    info = entries[0]
                path = self._result_path(info)
                if path is None or not path.exists():
                    candidates = sorted(
                        (item for item in out_dir.iterdir() if item.is_file() and not item.name.endswith(".part")),
                        key=lambda item: item.stat().st_mtime,
                        reverse=True,
                    )
                    path = candidates[0] if candidates else None
                if path is None:
                    raise DownloadError("errors.unknown", "output file missing")
                duration = int(info.get("duration") or media.duration or 0)
                width = info.get("width")
                height_value = info.get("height")
                if is_audio:
                    width, height_value = None, None
                return DownloadResult(
                    paths=[path],
                    info=info,
                    title=str(info.get("title") or media.title),
                    duration=duration,
                    width=int(width) if width else None,
                    height=int(height_value) if height_value else None,
                    size=path.stat().st_size,
                )
        except DownloadCancelled:
            raise
        except DownloadError:
            raise
        except Exception as exc:
            raise classify_error(exc) from exc

    @staticmethod
    def _result_path(info: dict[str, Any]) -> Path | None:
        requested = info.get("requested_downloads") or []
        for item in requested:
            for key in ("filepath", "_filename", "filename"):
                value = item.get(key)
                if value:
                    path = Path(value)
                    if path.exists():
                        return path
                    # Post-processed output may have a different extension.
                    for candidate in path.parent.glob(path.stem + ".*"):
                        if candidate.is_file() and not candidate.name.endswith((".part", ".ytdl")):
                            return candidate
        for key in ("filepath", "_filename", "filename"):
            value = info.get(key)
            if value:
                path = Path(value)
                if path.exists():
                    return path
                for candidate in path.parent.glob(path.stem + ".*"):
                    if candidate.is_file() and not candidate.name.endswith((".part", ".ytdl")):
                        return candidate
        return None

    async def download(
        self,
        media: MediaInfo,
        quality: str,
        out_dir: Path,
        job: Any,
        *,
        audio_format: str = "mp3",
        audio_bitrate: int = 192,
    ) -> DownloadResult:
        return await asyncio.to_thread(
            self.download_sync,
            media,
            quality,
            out_dir,
            job,
            audio_format=audio_format,
            audio_bitrate=audio_bitrate,
        )

    # ------------------------------------------------------------------ ffmpeg
    async def compress(
        self,
        source: Path,
        limit: int,
        out_dir: Path,
        *,
        on_status: Callable[[str], None] | None = None,
    ) -> Path | None:
        """Shrink a video until it fits Telegram's limit (best effort)."""
        if not self.cfg.ffmpeg_available or source.stat().st_size <= limit:
            return source if source.stat().st_size <= limit else None
        target = out_dir / "compressed.mp4"
        for height, crf in ((480, 30), (360, 31), (240, 33)):
            if on_status:
                on_status(f"compressing:{height}")
            output = out_dir / f"compressed_{height}.mp4"
            args = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-vf",
                f"scale=-2:'min({height},ih)'",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                str(crf),
                "-c:a",
                "aac",
                "-b:a",
                "64k",
                "-movflags",
                "+faststart",
                str(output),
            ]
            try:
                process = await asyncio.create_subprocess_exec(
                    *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
                )
                _, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=max(300, source.stat().st_size // 500_000)
                )
            except (TimeoutError, OSError) as exc:
                log.warning("compress failed: %s", exc)
                with contextlib.suppress(ProcessLookupError):
                    process.kill()  # type: ignore[possibly-undefined]
                return None
            if process.returncode != 0:
                log.warning("ffmpeg failed: %s", stderr.decode("utf-8", "ignore")[:500])
                continue
            if output.exists() and output.stat().st_size <= limit:
                return output
            if output.exists() and output.stat().st_size < source.stat().st_size:
                target = output
        return target if target.exists() and target.stat().st_size <= limit else None

    async def extract_audio(self, source: Path, out_dir: Path, *, bitrate: int = 192) -> Path | None:
        if not self.cfg.ffmpeg_available:
            return None
        output = out_dir / f"{source.stem}__{bitrate}k.mp3"
        args = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-b:a",
            f"{bitrate}k",
            str(output),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
            )
            await asyncio.wait_for(process.communicate(), timeout=600)
        except (TimeoutError, OSError) as exc:
            log.warning("extract_audio failed: %s", exc)
            return None
        return output if process.returncode == 0 and output.exists() else None

    async def probe_duration(self, source: Path) -> int:
        if not shutil.which("ffprobe"):
            return 0
        args = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
            return int(float(stdout.decode().strip() or 0))
        except (TimeoutError, OSError, ValueError):
            return 0
