"""URL extraction, platform detection and a few network safety helpers."""

from __future__ import annotations

import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bot.constants import PLATFORMS, Platform

_SCHEME_URL_RE = re.compile(r"(?i)\bhttps?://[^\s<>\"']+")
_WWW_URL_RE = re.compile(r"(?i)(?<![\w@])\bwww\.[^\s<>\"']+")
_TRAILING = ".,;:!?)]}»”'\"…،؛؟"
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)

_TRACKING_PARAMS = {
    "si",
    "pp",
    "fbclid",
    "gclid",
    "igshid",
    "igsh",
    "feature",
    "ref",
    "ref_src",
    "ref_url",
    "s",
    "t",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
}
_YOUTUBE_KEEP = {"v", "list", "index", "start", "t"}

_DOMAIN_ALIASES = {
    "youtu.be": "youtube.com",
    "m.youtube.com": "youtube.com",
    "music.youtube.com": "youtube.com",
    "youtube-nocookie.com": "youtube.com",
    "instagr.am": "instagram.com",
    "m.instagram.com": "instagram.com",
    "vt.tiktok.com": "tiktok.com",
    "vm.tiktok.com": "tiktok.com",
    "m.tiktok.com": "tiktok.com",
    "mobile.twitter.com": "x.com",
    "twitter.com": "x.com",
    "fb.watch": "facebook.com",
    "m.facebook.com": "facebook.com",
    "redd.it": "reddit.com",
    "v.redd.it": "reddit.com",
    "old.reddit.com": "reddit.com",
    "pin.it": "pinterest.com",
    "dai.ly": "dailymotion.com",
    "snd.sc": "soundcloud.com",
    "spotify.link": "open.spotify.com",
    "b23.tv": "bilibili.com",
    "vkvideo.ru": "vk.com",
    "telegram.me": "t.me",
}

_DOMAIN_TO_PLATFORM: dict[str, Platform] = {}
for _platform in PLATFORMS:
    for _domain in _platform.domains:
        _DOMAIN_TO_PLATFORM[_domain] = _platform
    _DOMAIN_TO_PLATFORM[_platform.code] = _platform

_VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".webm",
    ".mov",
    ".avi",
    ".flv",
    ".m4v",
    ".ts",
    ".m3u8",
    ".mpg",
    ".mpeg",
    ".wmv",
    ".3gp",
}
_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus", ".wma", ".aiff"}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
_DOC_EXTENSIONS = {
    ".pdf",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".apk",
    ".exe",
    ".dmg",
    ".iso",
    ".txt",
    ".srt",
    ".vtt",
    ".epub",
    ".json",
    ".csv",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
}
MEDIA_EXTENSIONS = _VIDEO_EXTENSIONS | _AUDIO_EXTENSIONS | _IMAGE_EXTENSIONS


def extract_urls(text: str | None) -> list[str]:
    """Extract unique, normalized URLs from a message, preserving their order."""
    if not text:
        return []
    text = text.translate(_ZERO_WIDTH)
    matches: list[tuple[int, str]] = []
    for pattern in (_SCHEME_URL_RE, _WWW_URL_RE):
        for match in pattern.finditer(text):
            value = match.group(0).rstrip(_TRAILING)
            if pattern is _WWW_URL_RE:
                value = "https://" + value
            matches.append((match.start(), value))

    # Bare domains of known platforms (youtube.com/watch?v=..., x.com/...).
    lowered = text.lower()
    for domain in _DOMAIN_TO_PLATFORM:
        if "." not in domain:
            continue
        index = lowered.find(domain)
        while index != -1:
            before = text[index - 1] if index > 0 else " "
            after_index = index + len(domain)
            after = text[after_index] if after_index < len(text) else " "
            if not (before.isalnum() or before in "@._-") and after not in "._-":
                tail_match = re.match(r"[^\s<>\"']*", text[after_index:])
                tail = tail_match.group(0) if tail_match else ""
                candidate = ("https://" + text[index:after_index] + tail).rstrip(_TRAILING)
                matches.append((index, candidate))
            index = lowered.find(domain, index + 1)

    matches.sort(key=lambda item: item[0])
    normalized: list[str] = []
    seen: set[str] = set()
    for _, value in matches:
        try:
            url = normalize_url(value)
        except ValueError:
            continue
        if url not in seen:
            seen.add(url)
            normalized.append(url)
    return normalized


def normalize_url(value: str) -> str:
    value = value.strip().translate(_ZERO_WIDTH)
    if value.startswith("//"):
        value = "https:" + value
    if not re.match(r"(?i)^https?://", value):
        value = "https://" + value
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"}:
        raise ValueError("unsupported scheme")
    if not parts.hostname:
        raise ValueError("missing host")
    host = parts.hostname.lower().strip(".")
    host = _DOMAIN_ALIASES.get(host, host)
    if host.startswith("www."):
        host = host[4:]
    netloc = host
    if parts.port and not (
        (parts.scheme == "http" and parts.port == 80) or (parts.scheme == "https" and parts.port == 443)
    ):
        netloc = f"{host}:{parts.port}"

    query_pairs = parse_qsl(parts.query, keep_blank_values=False)
    if host == "youtube.com":
        query_pairs = [(k, v) for k, v in query_pairs if k in _YOUTUBE_KEEP]
    else:
        query_pairs = [(k, v) for k, v in query_pairs if k not in _TRACKING_PARAMS and not k.startswith("utm_")]
    query = urlencode(query_pairs)
    path = re.sub(r"/{2,}", "/", parts.path) or ""
    return urlunsplit(("https" if parts.scheme == "https" else "http", netloc, path, query, ""))


def host_of(url: str) -> str:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    host = host.lower().lstrip(".")
    return _DOMAIN_ALIASES.get(host, host.removeprefix("www."))


def detect_platform(url: str) -> Platform:
    host = host_of(url)
    if not host:
        return _DOMAIN_TO_PLATFORM["direct"]
    for domain, platform in _DOMAIN_TO_PLATFORM.items():
        if "." not in domain:
            continue
        if host == domain or host.endswith("." + domain):
            return platform
    if is_direct_file(url):
        return _DOMAIN_TO_PLATFORM["direct"]
    return _DOMAIN_TO_PLATFORM["direct"]


def platform_name(code: str) -> tuple[str, str]:
    platform = next((p for p in PLATFORMS if p.code == code), None)
    if platform is None:
        return code, "🔗"
    return platform.name, platform.emoji


def is_direct_file(url: str) -> bool:
    try:
        path = urlsplit(url).path.lower()
    except ValueError:
        return False
    suffix = Path(path).suffix
    return suffix in MEDIA_EXTENSIONS | _DOC_EXTENSIONS


def is_video_url(url: str) -> bool:
    return Path(urlsplit(url).path.lower()).suffix in _VIDEO_EXTENSIONS


def is_audio_url(url: str) -> bool:
    return Path(urlsplit(url).path.lower()).suffix in _AUDIO_EXTENSIONS


def is_spotify(url: str) -> bool:
    return host_of(url) == "open.spotify.com"


def spotify_kind(url: str) -> str | None:
    path = urlsplit(url).path.strip("/")
    if not path:
        return None
    return path.split("/")[0]


def youtube_id(url: str) -> str | None:
    parts = urlsplit(url)
    raw_host = (parts.hostname or "").lower().removeprefix("www.")
    host = host_of(url)
    if raw_host == "youtu.be" or host == "youtu.be":
        return parts.path.strip("/").split("/")[0] or None
    if host == "youtube.com":
        query = dict(parse_qsl(parts.query))
        if "v" in query:
            return query["v"]
        match = re.search(r"/(?:shorts|embed|live|v)/([\w-]{6,})", parts.path)
        if match:
            return match.group(1)
    return None


def sanitize_filename(name: str, *, fallback: str = "TELRO_download", limit: int = 120) -> str:
    name = (name or "").strip().replace("\x00", "")
    name = re.sub(r"[\\/:*?\"<>|\r\n\t]", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = fallback
    if len(name) > limit:
        stem = Path(name).stem[: limit - 12].rstrip()
        suffix = Path(name).suffix[:10]
        name = stem + suffix
    return name


def safe_join(directory: Path, filename: str) -> Path:
    directory = Path(directory).resolve()
    candidate = (directory / sanitize_filename(filename)).resolve()
    if directory not in candidate.parents and candidate != directory:
        raise ValueError("path traversal detected")
    return candidate


async def is_safe_public_url(url: str, *, allowed_ports: set[int] | None = None) -> bool:
    """Reject localhost / private network targets to avoid SSRF."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in {"http", "https"}:
        return False
    if not parts.hostname:
        return False
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if allowed_ports is not None and port not in allowed_ports:
        return False
    host = parts.hostname.lower().strip("[]")
    if host in {"localhost", "localhost.localdomain", "0.0.0.0", "::1"} or host.endswith(".local"):
        return False
    try:
        infos = await _resolve(host, port)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            return False
    return True


async def _resolve(host: str, port: int) -> list:
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP),
    )
