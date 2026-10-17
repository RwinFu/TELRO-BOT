"""Shared constants used across the bot."""

from __future__ import annotations

from dataclasses import dataclass

# Telegram limits -----------------------------------------------------------------
TG_TEXT_LIMIT = 4096
TG_CAPTION_LIMIT = 1024
TG_ALBUM_LIMIT = 10
TG_CLOUD_UPLOAD_LIMIT = 50 * 1024 * 1024  # 50 MB via api.telegram.org
TG_LOCAL_UPLOAD_LIMIT = 2000 * 1024 * 1024  # 2 GB via a local Bot API server
TG_SAFE_UPLOAD_LIMIT = 1990 * 1024 * 1024

# App behaviour -------------------------------------------------------------------
VERSION = "1.0.0"
BRAND = "TELRO"
CACHE_TTL_DAYS = 30
PENDING_TTL_SECONDS = 60 * 60
DEEP_LINK_TTL_SECONDS = 60 * 60
MUSIC_SEARCH_TTL_SECONDS = 15 * 60
INSPECT_CACHE_TTL_SECONDS = 15 * 60
PROGRESS_INTERVAL = 1.2
CLEANUP_INTERVAL = 60 * 30
DOWNLOAD_MAX_AGE_SECONDS = 3 * 60 * 60

# Quality presets -----------------------------------------------------------------
QUALITY_HEIGHTS = (2160, 1440, 1080, 720, 480, 360, 240, 144)
QUALITY_LABELS = {
    4320: "8K",
    2160: "4K",
    1440: "2K",
    1080: "FHD",
    720: "HD",
    480: "SD",
    360: "360p",
    240: "240p",
    144: "144p",
}
AUDIO_BITRATES = (320, 192, 128, 96, 64)


@dataclass(frozen=True, slots=True)
class Platform:
    """Human friendly description of a supported website."""

    code: str
    name: str
    emoji: str
    domains: tuple[str, ...]


PLATFORMS: tuple[Platform, ...] = (
    Platform("youtube", "یوتیوب", "▶️", ("youtube.com", "youtu.be", "youtube-nocookie.com", "music.youtube.com")),
    Platform("instagram", "اینستاگرام", "📸", ("instagram.com", "instagr.am")),
    Platform("tiktok", "تیک‌تاک", "🎵", ("tiktok.com", "vt.tiktok.com", "vm.tiktok.com")),
    Platform("twitter", "ایکس (توییتر)", "🐦", ("twitter.com", "x.com", "t.co")),
    Platform("facebook", "فیسبوک", "📘", ("facebook.com", "fb.watch", "fb.com")),
    Platform("reddit", "ردیت", "👽", ("reddit.com", "redd.it", "v.redd.it")),
    Platform("pinterest", "پینترست", "📌", ("pinterest.com", "pin.it", "pinterest.de")),
    Platform("threads", "تردز", "🧵", ("threads.net", "threads.com")),
    Platform("vimeo", "ویمئو", "🎬", ("vimeo.com",)),
    Platform("dailymotion", "دیلی‌موشن", "📺", ("dailymotion.com", "dai.ly")),
    Platform("soundcloud", "ساندکلاد", "🔊", ("soundcloud.com", "snd.sc")),
    Platform("spotify", "اسپاتیفای", "🟢", ("open.spotify.com", "spotify.link")),
    Platform("aparat", "آپارات", "🎞", ("aparat.com", "aparat.ir")),
    Platform("twitch", "توئیچ", "🎮", ("twitch.tv", "clips.twitch.tv")),
    Platform("bilibili", "بیلی‌بیلی", "📺", ("bilibili.com", "b23.tv")),
    Platform("vk", "وی‌کی", "🇷🇺", ("vk.com", "vkvideo.ru")),
    Platform("ok", "اوکی", "🟠", ("ok.ru",)),
    Platform("rutube", "روتیوب", "🔴", ("rutube.ru",)),
    Platform("likee", "لایکی", "✨", ("likee.video", "likee.com")),
    Platform("snapchat", "اسنپ‌چت", "👻", ("snapchat.com",)),
    Platform("linkedin", "لینکدین", "💼", ("linkedin.com",)),
    Platform("imgur", "ایمجور", "🖼", ("imgur.com",)),
    Platform("streamable", "استریمبل", "🎥", ("streamable.com",)),
    Platform("telegram", "تلگرام", "✈️", ("t.me", "telegram.me")),
    Platform("direct", "فایل مستقیم", "🔗", ()),
)

PLATFORM_BY_CODE: dict[str, Platform] = {p.code: p for p in PLATFORMS}

UNIQUE_TOKEN = "TELRO"

# Callback prefixes ---------------------------------------------------------------
CB_MENU = "menu"
CB_BACK = "back"
CB_QUALITY = "q"
CB_PLAYLIST = "pl"
CB_CANCEL = "cancel"
CB_RETRY = "retry"
CB_SETTINGS = "set"
CB_ACCOUNT = "acc"
CB_AI = "ai"
CB_IMAGE = "img"
CB_MUSIC = "m"
CB_ADMIN = "adm"
CB_JOIN = "join"
