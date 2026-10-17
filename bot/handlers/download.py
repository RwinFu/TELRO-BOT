"""Link handling: inspect, show a quality picker and start downloads."""

from __future__ import annotations

import logging
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message

from bot.config import Settings
from bot.constants import PLATFORMS
from bot.db.repository import Repository, User
from bot.handlers.common import platform_list
from bot.i18n import i18n
from bot.keyboards.inline import back_menu, playlist_keyboard, quality_keyboard
from bot.services.downloader.direct import DirectDownloader, DirectFile
from bot.services.downloader.errors import DownloadError
from bot.services.downloader.formats import MediaInfo
from bot.services.downloader.inspector import Inspector
from bot.services.downloader.manager import DownloadManager, JobItem
from bot.utils.formatting import compact_number, human_bytes, human_duration, truncate
from bot.utils.telegram import answer_callback, safe_edit
from bot.utils.text import esc
from bot.utils.urls import detect_platform, extract_urls, is_direct_file, is_safe_public_url, platform_name

log = logging.getLogger(__name__)
router = Router(name="download")

_DOMAIN_HINT = "|".join(re.escape(domain) for p in PLATFORMS for domain in p.domains if "." in domain)
LINK_HINT = re.compile(rf"(?i)(https?://|www\.|(?:{_DOMAIN_HINT}))")


def quota_allowed(cfg: Settings, user: User) -> bool:
    return user.is_premium or user.id in cfg.admins or user.downloads_today < cfg.free_downloads_per_day


def quota_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=i18n.get(lang, "buttons.premium"), callback_data="menu:premium")],
            [InlineKeyboardButton(text=i18n.get(lang, "buttons.menu"), callback_data="menu:main")],
        ]
    )


def _meta_line(media: MediaInfo, lang: str) -> str:
    name, emoji = platform_name(media.platform)
    parts: list[str] = []
    if media.uploader:
        parts.append(f"👤 {esc(truncate(media.uploader, 40))}")
    if media.duration:
        parts.append(f"⏱ {human_duration(media.duration)}")
    if media.view_count:
        parts.append(f"👁 {compact_number(media.view_count)}")
    parts.append(f"{emoji} {esc(name)}")
    if media.is_live:
        parts.append(i18n.get(lang, "download.live"))
    return " · ".join(parts)


def _auto_quality(media: MediaInfo, preference: str) -> str | None:
    if preference == "best" and media.best is not None:
        return media.best.callback_value
    if preference in {"", "ask"}:
        return None
    option = media.find(preference)
    return option.callback_value if option else None


def _direct_keyboard(lang: str, token: str, file: DirectFile, *, ffmpeg: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=i18n.get(lang, "download.file_button", size=human_bytes(file.size)),
                callback_data=f"q:{token}:file",
            )
        ]
    ]
    if file.kind == "video" and ffmpeg:
        rows.append(
            [InlineKeyboardButton(text=i18n.get(lang, "download.audio_button"), callback_data=f"q:{token}:audio")]
        )
    rows.append([InlineKeyboardButton(text=i18n.get(lang, "buttons.cancel"), callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_card(
    message: Message,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
    *,
    preview_url: str | None = None,
) -> Message:
    options = (
        LinkPreviewOptions(url=preview_url, prefer_large_media=True, show_above_text=True)
        if preview_url
        else LinkPreviewOptions(is_disabled=True)
    )
    try:
        return await message.answer(text, reply_markup=keyboard, link_preview_options=options)
    except Exception:
        return await message.answer(
            text, reply_markup=keyboard, link_preview_options=LinkPreviewOptions(is_disabled=True)
        )


async def begin_download(
    message: Message,
    url: str,
    user: User,
    *,
    cfg: Settings,
    repo: Repository,
    bot: Bot,
    inspector: Inspector,
    direct: DirectDownloader,
    manager: DownloadManager,
    prefer_audio: bool = False,
    status_message: Message | None = None,
) -> Message | None:
    """Inspect a URL and either start an audio download or show the picker."""
    del bot
    lang = user.language
    if not quota_allowed(cfg, user):
        text = i18n.get(lang, "download.quota", used=user.downloads_today, limit=cfg.free_downloads_per_day)
        if status_message is not None:
            await safe_edit(status_message, text, quota_keyboard(lang))
            return status_message
        await message.answer(text, reply_markup=quota_keyboard(lang))
        return None

    status = status_message
    if status is None:
        status = await _send_card(message, i18n.get(lang, "download.detecting", url=esc(truncate(url, 120))))

    platform = detect_platform(url)
    if platform.code == "direct" and not await is_safe_public_url(url):
        await safe_edit(
            status,
            i18n.get(lang, "download.failed", error=i18n.get(lang, "errors.unsafe_url")),
            back_menu(lang),
        )
        return status

    # Plain direct file links are handled by a small HTTP client (fast + no yt-dlp).
    if platform.code == "direct" and is_direct_file(url):
        try:
            file = await direct.probe(url)
        except DownloadError as exc:
            await safe_edit(
                status,
                i18n.get(lang, "download.failed", error=i18n.get(lang, exc.key)),
                back_menu(lang),
            )
            return status
        token = await repo.pending_create(
            "direct",
            user_id=user.id,
            url=file.url,
            payload={
                "filename": file.filename,
                "size": file.size,
                "content_type": file.content_type,
                "kind": file.kind,
            },
        )
        kind_label = i18n.get(lang, f"download.kind_{file.kind}")
        text = i18n.get(
            lang,
            "download.direct_card",
            filename=esc(truncate(file.filename, 100)),
            size=human_bytes(file.size),
            kind=kind_label,
        )
        keyboard = _direct_keyboard(lang, token, file, ffmpeg=cfg.ffmpeg_available)
        await safe_edit(status, text, keyboard)
        return status

    try:
        media = await inspector.inspect(url)
    except DownloadError as exc:
        # Unknown hosts may still be direct files (CDNs etc.).
        if platform.code == "direct":
            try:
                file = await direct.probe(url)
            except DownloadError:
                await safe_edit(
                    status,
                    i18n.get(lang, "download.failed", error=i18n.get(lang, exc.key)),
                    back_menu(lang),
                )
                return status
            token = await repo.pending_create(
                "direct",
                user_id=user.id,
                url=file.url,
                payload={
                    "filename": file.filename,
                    "size": file.size,
                    "content_type": file.content_type,
                    "kind": file.kind,
                },
            )
            text = i18n.get(
                lang,
                "download.direct_card",
                filename=esc(truncate(file.filename, 100)),
                size=human_bytes(file.size),
                kind=i18n.get(lang, f"download.kind_{file.kind}"),
            )
            await safe_edit(status, text, _direct_keyboard(lang, token, file, ffmpeg=cfg.ffmpeg_available))
            return status
        await safe_edit(
            status,
            i18n.get(lang, "download.failed", error=i18n.get(lang, exc.key)),
            back_menu(lang),
        )
        return status

    if media.is_playlist and prefer_audio and media.entries:
        media = await inspector.inspect(media.entries[0])

    if media.is_playlist:
        token = await repo.pending_create("playlist", user_id=user.id, url=url, payload=media.to_payload())
        await safe_edit(
            status,
            i18n.get(lang, "download.playlist_title", title=esc(truncate(media.title, 100)), count=media.entry_count),
            playlist_keyboard(lang, token, media.entry_count),
        )
        return status

    auto = _auto_quality(media, user.pref_quality) if not prefer_audio else None
    if auto:
        allowed, used = await repo.consume_download(
            user.id, cfg.free_downloads_per_day, unlimited=user.is_premium or user.id in cfg.admins
        )
        if not allowed:
            await safe_edit(
                status,
                i18n.get(lang, "download.quota", used=used, limit=cfg.free_downloads_per_day),
                quota_keyboard(lang),
            )
            return status
        job = manager.create_job(
            user, status, media=media, quality=auto, platform=media.platform, title=media.title
        )
        manager.start(job)
        return status

    if prefer_audio:
        allowed, used = await repo.consume_download(
            user.id, cfg.free_downloads_per_day, unlimited=user.is_premium or user.id in cfg.admins
        )
        if not allowed:
            await safe_edit(
                status,
                i18n.get(lang, "download.quota", used=used, limit=cfg.free_downloads_per_day),
                quota_keyboard(lang),
            )
            return status
        job = manager.create_job(
            user, status, media=media, quality="audio", platform=media.platform, title=media.title
        )
        manager.start(job)
        return status

    token = await repo.pending_create("media", user_id=user.id, url=url, payload=media.to_payload())
    text = i18n.get(
        lang,
        "download.card",
        title=esc(truncate(media.title, 140)),
        meta=_meta_line(media, lang),
    )
    await safe_edit(status, text, quality_keyboard(lang, media, token))
    return status


@router.message(Command("dl", "download"))
async def cmd_dl(
    message: Message,
    command,
    user: User,
    state: FSMContext,
    cfg: Settings,
    repo: Repository,
    bot: Bot,
    inspector: Inspector,
    direct: DirectDownloader,
    manager: DownloadManager,
) -> None:
    text = command.args or ""
    if not text and message.reply_to_message is not None:
        text = message.reply_to_message.text or message.reply_to_message.caption or ""
    urls = extract_urls(text)
    if not urls:
        await message.answer(i18n.get(user.language, "download.not_link"))
        return
    await state.clear()
    await begin_download(
        message,
        urls[0],
        user,
        cfg=cfg,
        repo=repo,
        bot=bot,
        inspector=inspector,
        direct=direct,
        manager=manager,
    )


@router.message(F.text.regexp(LINK_HINT))
async def on_link_message(
    message: Message,
    user: User,
    state: FSMContext,
    cfg: Settings,
    repo: Repository,
    bot: Bot,
    inspector: Inspector,
    direct: DirectDownloader,
    manager: DownloadManager,
) -> None:
    if message.chat.type != "private":
        if not cfg.enable_groups or not await is_group_trigger(message, cfg):
            return
    urls = extract_urls(message.text)
    if not urls:
        return
    if len(urls) > 1:
        await message.answer(i18n.get(user.language, "download.too_many"))
    await state.clear()
    await begin_download(
        message,
        urls[0],
        user,
        cfg=cfg,
        repo=repo,
        bot=bot,
        inspector=inspector,
        direct=direct,
        manager=manager,
    )


async def is_group_trigger(message: Message, cfg: Settings) -> bool:
    text = message.text or ""
    if f"@{cfg.bot_username.lower()}" in text.lower():
        return True
    if message.reply_to_message and message.reply_to_message.from_user and message.bot is not None:
        if message.reply_to_message.from_user.id == message.bot.id:
            return True
    return False


@router.callback_query(F.data == "menu:download")
async def cb_download_intro(callback: CallbackQuery, user: User, cfg: Settings) -> None:
    lang = user.language
    text = f"{i18n.get(lang, 'download.title')}\n\n" + i18n.get(
        lang, "download.intro", limit=cfg.max_upload_label, platforms=platform_list()
    )
    if callback.message is not None:
        await safe_edit(callback.message, text, back_menu(lang))
    await answer_callback(callback)


@router.callback_query(F.data.startswith("q:"))
async def cb_quality(
    callback: CallbackQuery,
    user: User,
    cfg: Settings,
    repo: Repository,
    manager: DownloadManager,
    state: FSMContext,
) -> None:
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3:
        await answer_callback(callback)
        return
    _, token, quality = parts
    pending = await repo.pending_get(token)
    if pending is None or pending["user_id"] != user.id:
        await answer_callback(callback, i18n.get(user.language, "download.expired"), alert=True)
        return
    if not quota_allowed(cfg, user):
        await answer_callback(
            callback,
            i18n.get(user.language, "download.quota", used=user.downloads_today, limit=cfg.free_downloads_per_day),
            alert=True,
        )
        return
    allowed, used = await repo.consume_download(
        user.id, cfg.free_downloads_per_day, unlimited=user.is_premium or user.id in cfg.admins
    )
    if not allowed:
        await answer_callback(
            callback,
            i18n.get(user.language, "download.quota", used=used, limit=cfg.free_downloads_per_day),
            alert=True,
        )
        return
    if callback.message is None:
        await answer_callback(callback)
        return

    if pending["kind"] == "media":
        media = MediaInfo.from_payload(pending["payload"] or {})
        chosen = quality
        if chosen == "best":
            best = media.best
            chosen = str(best.height) if best and best.height else "best"
        job = manager.create_job(
            user,
            callback.message,
            media=media,
            quality=chosen,
            platform=media.platform,
            token=token,
            title=media.title,
        )
        await state.clear()
    elif pending["kind"] == "direct":
        payload = pending["payload"] or {}
        file = DirectFile(
            url=pending["url"] or "",
            filename=str(payload.get("filename") or "download"),
            size=payload.get("size"),
            content_type=str(payload.get("content_type") or "application/octet-stream"),
            kind=str(payload.get("kind") or "document"),
        )
        chosen = "audio" if quality == "audio" and file.kind in {"video", "audio"} else "file"
        job = manager.create_job(
            user,
            callback.message,
            direct_file=file,
            quality=chosen,
            platform="direct",
            token=token,
            title=file.filename,
        )
    else:
        await answer_callback(callback, i18n.get(user.language, "download.expired"))
        return
    await answer_callback(callback, i18n.get(user.language, "download.requested"))
    manager.start(job)


@router.callback_query(F.data.startswith("pl:"))
async def cb_playlist(
    callback: CallbackQuery,
    user: User,
    cfg: Settings,
    repo: Repository,
    manager: DownloadManager,
    state: FSMContext,
) -> None:
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3 or callback.message is None:
        await answer_callback(callback)
        return
    _, token, choice = parts
    pending = await repo.pending_get(token)
    if pending is None or pending["user_id"] != user.id or pending["kind"] != "playlist":
        await answer_callback(callback, i18n.get(user.language, "download.expired"), alert=True)
        return
    payload = pending["payload"] or {}
    entries = [str(item) for item in payload.get("entries") or [] if item]
    if not entries:
        await answer_callback(callback, i18n.get(user.language, "download.expired"), alert=True)
        return
    selected = entries[:10] if choice == "all" else entries[:1]
    if not quota_allowed(cfg, user):
        await answer_callback(
            callback,
            i18n.get(user.language, "download.quota", used=user.downloads_today, limit=cfg.free_downloads_per_day),
            alert=True,
        )
        return
    allowed, used = await repo.consume_download(
        user.id, cfg.free_downloads_per_day, unlimited=user.is_premium or user.id in cfg.admins
    )
    if not allowed:
        await answer_callback(
            callback,
            i18n.get(user.language, "download.quota", used=used, limit=cfg.free_downloads_per_day),
            alert=True,
        )
        return
    job = manager.create_job(
        user,
        callback.message,
        platform=str(payload.get("platform") or "youtube"),
        quality="best",
        token=token,
        title=str(payload.get("title") or ""),
        items=[JobItem(url=entry, quality="best") for entry in selected],
    )
    await state.clear()
    await answer_callback(callback, i18n.get(user.language, "download.requested"))
    manager.start(job)


@router.callback_query(F.data.startswith("cancel:"))
async def cb_cancel(callback: CallbackQuery, user: User, manager: DownloadManager) -> None:
    job_id = (callback.data or "").split(":", 1)[-1]
    ok = await manager.cancel(user.id, job_id)
    await answer_callback(callback, i18n.get(user.language, "download.cancelled") if ok else None)


@router.callback_query(F.data.startswith("delete:"))
async def cb_delete(callback: CallbackQuery, user: User) -> None:
    if callback.message is None:
        await answer_callback(callback)
        return
    parts = (callback.data or "").split(":", 1)
    if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) != user.id:
        await answer_callback(callback, i18n.get(user.language, "access.admin_only"), alert=True)
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    await answer_callback(callback)
