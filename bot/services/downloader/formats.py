"""Choose sensible formats and estimate their size before downloading."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bot.utils.formatting import human_bytes, quality_label

VIDEO_EXTENSIONS = {"mp4", "mkv", "webm", "mov"}


@dataclass(slots=True)
class QualityOption:
    height: int
    label: str
    size: int | None = None
    ext: str = "mp4"
    fps: int | None = None
    is_audio: bool = False

    @property
    def callback_value(self) -> str:
        return "audio" if self.is_audio else str(self.height or "best")

    @property
    def button_text(self) -> str:
        if self.is_audio:
            size = f" · ~{human_bytes(self.size)}" if self.size else ""
            return f"🎵 MP3{size}"
        label = self.label or quality_label(self.height)
        size = f" · ~{human_bytes(self.size)}" if self.size else ""
        return f"🎬 {label}{size}"


@dataclass(slots=True)
class MediaInfo:
    url: str
    platform: str
    media_id: str
    title: str
    download_url: str = ""
    uploader: str = ""
    duration: int = 0
    view_count: int | None = None
    thumbnail: str | None = None
    webpage_url: str = ""
    qualities: list[QualityOption] = field(default_factory=list)
    audio_size: int | None = None
    is_playlist: bool = False
    entry_count: int = 0
    entries: list[str] = field(default_factory=list)
    is_live: bool = False
    is_audio_only: bool = False

    @property
    def target(self) -> str:
        return self.download_url or self.url

    @property
    def best(self) -> QualityOption | None:
        for option in self.qualities:
            if not option.is_audio:
                return option
        return self.qualities[0] if self.qualities else None

    def find(self, value: str) -> QualityOption | None:
        if value == "audio":
            return next((option for option in self.qualities if option.is_audio), None)
        if value == "best":
            return self.best
        for option in self.qualities:
            if str(option.height) == str(value):
                return option
        return None

    def to_payload(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "download_url": self.download_url,
            "platform": self.platform,
            "media_id": self.media_id,
            "title": self.title,
            "uploader": self.uploader,
            "duration": self.duration,
            "view_count": self.view_count,
            "thumbnail": self.thumbnail,
            "webpage_url": self.webpage_url,
            "audio_size": self.audio_size,
            "is_audio_only": self.is_audio_only,
            "is_playlist": self.is_playlist,
            "entry_count": self.entry_count,
            "entries": self.entries[:25],
            "qualities": [
                {
                    "height": option.height,
                    "label": option.label,
                    "size": option.size,
                    "ext": option.ext,
                    "fps": option.fps,
                    "is_audio": option.is_audio,
                }
                for option in self.qualities
            ],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> MediaInfo:
        qualities = [
            QualityOption(
                height=int(item.get("height") or 0),
                label=str(item.get("label") or ""),
                size=item.get("size"),
                ext=str(item.get("ext") or "mp4"),
                fps=item.get("fps"),
                is_audio=bool(item.get("is_audio")),
            )
            for item in payload.get("qualities") or []
        ]
        return cls(
            url=str(payload.get("url") or ""),
            platform=str(payload.get("platform") or "direct"),
            download_url=str(payload.get("download_url") or ""),
            media_id=str(payload.get("media_id") or ""),
            title=str(payload.get("title") or ""),
            uploader=str(payload.get("uploader") or ""),
            duration=int(payload.get("duration") or 0),
            view_count=payload.get("view_count"),
            thumbnail=payload.get("thumbnail"),
            webpage_url=str(payload.get("webpage_url") or ""),
            qualities=qualities,
            audio_size=payload.get("audio_size"),
            is_playlist=bool(payload.get("is_playlist")),
            entry_count=int(payload.get("entry_count") or 0),
            entries=[str(item) for item in payload.get("entries") or []],
            is_audio_only=bool(payload.get("is_audio_only")),
        )


def _size(fmt: dict[str, Any]) -> int | None:
    value = fmt.get("filesize") or fmt.get("filesize_approx")
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _score(fmt: dict[str, Any]) -> float:
    score = 0.0
    ext = str(fmt.get("ext") or "").lower()
    vcodec = str(fmt.get("vcodec") or "")
    acodec = str(fmt.get("acodec") or "")
    if ext == "mp4":
        score += 120
    if vcodec.startswith(("avc1", "h264", "avc3")):
        score += 100
    if acodec and acodec != "none":
        score += 45
    if ext in {"webm", "mkv"}:
        score += 10
    tbr = fmt.get("tbr") or 0
    try:
        score += min(float(tbr), 20000) / 1000
    except (TypeError, ValueError):
        pass
    return score


def _audio_estimate(info: dict[str, Any], formats: list[dict[str, Any]]) -> int | None:
    audio_sizes = [
        _size(fmt)
        for fmt in formats
        if fmt.get("acodec") not in (None, "none") and fmt.get("vcodec") in (None, "none") and _size(fmt)
    ]
    if audio_sizes:
        return max(audio_sizes)
    duration = info.get("duration")
    if duration:
        try:
            return int(float(duration) * 128_000 / 8)
        except (TypeError, ValueError):
            return None
    return None


def build_qualities(info: dict[str, Any], *, include_audio: bool = True) -> tuple[list[QualityOption], int | None]:
    """Return selectable video qualities (descending) and the audio size."""
    formats = [fmt for fmt in info.get("formats") or [] if isinstance(fmt, dict)]
    if not formats:
        height = int(info.get("height") or 0)
        size = _size(info) or info.get("filesize_approx")
        qualities = [
            QualityOption(
                height=height,
                label=quality_label(height),
                size=int(size) if size else None,
                ext=str(info.get("ext") or "mp4"),
                fps=info.get("fps"),
            )
        ]
        if include_audio:
            qualities.append(QualityOption(height=0, label="MP3", size=None, is_audio=True))
        return qualities, None

    audio_size = _audio_estimate(info, formats)
    by_height: dict[int, dict[str, Any]] = {}
    for fmt in formats:
        height = fmt.get("height")
        if not height or fmt.get("vcodec") in (None, "none"):
            continue
        if fmt.get("ext") in {"mhtml", "none"} or fmt.get("format_note") == "storyboard":
            continue
        height = int(height)
        if height < 120 or height > 4320:
            continue
        current = by_height.get(height)
        if current is None or _score(fmt) > _score(current):
            by_height[height] = fmt

    max_height = max(by_height) if by_height else 0
    qualities: list[QualityOption] = []
    for height in sorted(by_height, reverse=True)[:8]:
        fmt = by_height[height]
        size = _size(fmt)
        if size is not None and str(fmt.get("acodec") or "none") == "none":
            size = size + (audio_size or 0)
        ext = str(fmt.get("ext") or "mp4")
        if ext not in VIDEO_EXTENSIONS:
            ext = "mp4"
        qualities.append(
            QualityOption(
                height=height,
                label=quality_label(height),
                size=size or None,
                ext=ext,
                fps=fmt.get("fps"),
            )
        )

    # If every available format is an audio-only stream, don't fabricate video rows.
    if not qualities:
        max_height = 0
        size = _size(info)
        if info.get("vcodec") not in (None, "none"):
            qualities.append(
                QualityOption(
                    height=int(info.get("height") or 0) or max_height,
                    label=quality_label(info.get("height")),
                    size=size,
                    ext=str(info.get("ext") or "mp4"),
                )
            )

    if include_audio:
        qualities.append(QualityOption(height=0, label="MP3", size=audio_size, is_audio=True))
    return qualities, audio_size


def format_selector(height: int, quality: str = "video") -> str:
    """yt-dlp format expression preferring Telegram friendly H.264/AAC MP4."""
    if quality == "audio":
        return "ba[acodec^=mp4a]/ba/b"
    if quality == "document":
        return "bv*+ba/b"
    if not height or height <= 0:
        return "bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
    h = int(height)
    return (
        f"bv*[height<={h}][ext=mp4][vcodec^=avc1]+ba[ext=m4a]/"
        f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/"
        f"b[height<={h}][ext=mp4]/"
        f"bv*[height<={h}]+ba/b[height<={h}]/"
        f"bv*[height<={h}]+ba/b"
    )


def audio_format_selector() -> str:
    return "ba[acodec^=mp4a]/ba/b"


def quality_cache_key(info: dict[str, Any] | MediaInfo, quality: str) -> str:
    platform = info.platform if isinstance(info, MediaInfo) else str(info.get("extractor_key") or "").lower()
    media_id = info.media_id if isinstance(info, MediaInfo) else str(info.get("id") or "")
    if not media_id:
        media_id = str(abs(hash(info.url if isinstance(info, MediaInfo) else info.get("webpage_url") or "")))
    return f"{platform}:{media_id}:{quality}"
