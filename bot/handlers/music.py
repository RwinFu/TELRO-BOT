"""Music search and MP3 downloads."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from bot.config import Settings
from bot.db.repository import Repository, User
from bot.handlers.download import begin_download
from bot.handlers.states import ChatStates
from bot.i18n import i18n
from bot.keyboards.inline import back_menu, music_results
from bot.services.downloader.direct import DirectDownloader
from bot.services.downloader.errors import DownloadError
from bot.services.downloader.inspector import Inspector, SearchResult
from bot.services.downloader.manager import DownloadManager, JobItem
from bot.utils.telegram import answer_callback, safe_edit
from bot.utils.text import esc
from bot.utils.urls import extract_urls

log = logging.getLogger(__name__)
router = Router(name="music")


@router.message(Command("music", "song", "mp3"))
async def cmd_music(
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
    query = (command.args or "").strip()
    if not query and message.reply_to_message is not None:
        query = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()
    if not query:
        await state.set_state(ChatStates.music)
        await message.answer(
            f"{i18n.get(user.language, 'music.title')}\n\n{i18n.get(user.language, 'music.intro')}",
            reply_markup=back_menu(user.language),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        return
    await _search_or_download(
        message,
        query,
        user,
        state=state,
        cfg=cfg,
        repo=repo,
        bot=bot,
        inspector=inspector,
        direct=direct,
        manager=manager,
    )


@router.callback_query(F.data == "menu:music")
async def cb_music(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await state.set_state(ChatStates.music)
    text = f"{i18n.get(user.language, 'music.title')}\n\n{i18n.get(user.language, 'music.intro')}"
    if callback.message is not None:
        await safe_edit(callback.message, text, back_menu(user.language))
    await answer_callback(callback)


@router.message(ChatStates.music, F.text, ~F.text.startswith("/"))
async def on_music_query(
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
    text = (message.text or "").strip()
    if not text:
        return
    await _search_or_download(
        message,
        text,
        user,
        state=state,
        cfg=cfg,
        repo=repo,
        bot=bot,
        inspector=inspector,
        direct=direct,
        manager=manager,
    )


async def _search_or_download(
    message: Message,
    query: str,
    user: User,
    *,
    state: FSMContext,
    cfg: Settings,
    repo: Repository,
    bot: Bot,
    inspector: Inspector,
    direct: DirectDownloader,
    manager: DownloadManager,
) -> None:
    lang = user.language
    urls = extract_urls(query)
    if urls:
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
            prefer_audio=True,
        )
        return
    if len(query) < 2:
        await message.answer(i18n.get(lang, "music.too_short"))
        return

    status = await message.answer(
        i18n.get(lang, "music.searching", query=esc(query[:80])),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    try:
        results = await inspector.search(query, limit=5)
    except DownloadError as exc:
        await safe_edit(
            status,
            i18n.get(lang, "download.failed", error=i18n.get(lang, exc.key)),
            back_menu(lang),
        )
        return
    if not results:
        await safe_edit(status, i18n.get(lang, "music.no_results", query=esc(query[:80])), back_menu(lang))
        return
    token = await repo.pending_create(
        "music",
        user_id=user.id,
        payload={"query": query, "results": [result.to_payload() for result in results]},
    )
    await state.clear()
    await safe_edit(
        status,
        i18n.get(lang, "music.results", query=esc(query[:80])),
        music_results(lang, token, results),
    )


@router.callback_query(F.data.startswith("m:"))
async def cb_music_pick(
    callback: CallbackQuery,
    user: User,
    cfg: Settings,
    repo: Repository,
    manager: DownloadManager,
    state: FSMContext,
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or callback.message is None:
        await answer_callback(callback)
        return
    token, raw_index = parts[1], parts[2]
    pending = await repo.pending_get(token)
    if pending is None or pending["user_id"] != user.id or pending["kind"] != "music":
        await answer_callback(callback, i18n.get(user.language, "music.expired"), alert=True)
        return
    if not raw_index.isdigit():
        await answer_callback(callback)
        return
    payload = pending["payload"] or {}
    results = [SearchResult.from_payload(item) for item in payload.get("results") or []]
    index = int(raw_index)
    if index < 0 or index >= len(results):
        await answer_callback(callback, i18n.get(user.language, "music.expired"), alert=True)
        return
    result = results[index]
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
        platform="youtube",
        quality="audio",
        token=token,
        title=result.title,
        items=[JobItem(url=result.url, quality="audio")],
    )
    await state.clear()
    await answer_callback(callback, i18n.get(user.language, "download.requested"))
    manager.start(job)
