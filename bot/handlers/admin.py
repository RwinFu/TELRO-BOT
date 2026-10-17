"""Admin panel: stats, broadcasts, user management and maintenance."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.db.repository import Repository, User
from bot.handlers.common import human_uptime
from bot.handlers.states import AdminStates
from bot.i18n import i18n
from bot.keyboards.inline import (
    admin_back,
    admin_menu,
    cancel_broadcast,
    main_menu,
    user_actions,
)
from bot.middlewares.admin import AdminGuard
from bot.services.downloader.manager import DownloadManager
from bot.utils.formatting import human_bytes
from bot.utils.telegram import answer_callback, safe_edit
from bot.utils.text import esc
from bot.utils.time import fmt_date, now_ts
from bot.utils.urls import platform_name

log = logging.getLogger(__name__)
router = Router(name="admin")
router.message.middleware(AdminGuard())
router.callback_query.middleware(AdminGuard())

_running = False
_cancel = False


def _panel(lang: str) -> str:
    return f"{i18n.get(lang, 'admin.title')}\n\n{i18n.get(lang, 'admin.body')}"


@router.message(Command("admin"))
async def cmd_admin(message: Message, user: User, repo: Repository) -> None:
    maintenance = await repo.get_bool_setting("maintenance", False)
    await message.answer(_panel(user.language), reply_markup=admin_menu(user.language, maintenance))


@router.callback_query(F.data == "menu:admin")
async def cb_admin(callback: CallbackQuery, user: User, repo: Repository) -> None:
    if callback.message is None:
        await answer_callback(callback)
        return
    maintenance = await repo.get_bool_setting("maintenance", False)
    await safe_edit(callback.message, _panel(user.language), admin_menu(user.language, maintenance))
    await answer_callback(callback)


@router.callback_query(F.data == "adm:stats")
async def cb_stats(
    callback: CallbackQuery,
    user: User,
    repo: Repository,
    cfg: Settings,
    manager: DownloadManager,
    started_at: float,
) -> None:
    if callback.message is None:
        await answer_callback(callback)
        return
    stats = await repo.stats()
    lang = user.language
    top = (
        "\n".join(
            f"• {platform_name(code)[1]} {platform_name(code)[0]} — {count}" for code, count in stats["top_platforms"]
        )
        or "—"
    )
    text = i18n.get(
        lang,
        "admin.stats_body",
        users=stats["users_total"],
        today=stats["users_today"],
        week=stats["users_week"],
        premium=stats["premium"],
        banned=stats["banned"],
        d_today=stats["downloads_today"],
        done=stats["downloads_done_today"],
        failed=stats["downloads_failed_today"],
        d_total=stats["downloads_total"],
        bytes=human_bytes(stats["downloads_bytes"]),
        ai_today=stats["ai_today"],
        ai_total=stats["ai_total"],
        cache=stats["cache_count"],
        hits=stats["cache_hits"],
        avg=f"{stats['avg_download_ms'] / 1000:.1f}s",
        jobs=manager.active_count,
        uptime=human_uptime(max(0, now_ts() - started_at)),
        top=top,
    )
    await safe_edit(callback.message, text, admin_back(lang))
    await answer_callback(callback)


@router.callback_query(F.data == "adm:maintenance")
async def cb_maintenance(callback: CallbackQuery, user: User, repo: Repository) -> None:
    current = await repo.get_bool_setting("maintenance", False)
    await repo.set_setting("maintenance", "0" if current else "1")
    lang = user.language
    message = i18n.get(lang, "admin.maintenance_disabled" if current else "admin.maintenance_enabled")
    if callback.message is not None:
        await safe_edit(callback.message, _panel(lang), admin_menu(lang, not current))
    await answer_callback(callback, message)


@router.callback_query(F.data == "adm:cache")
async def cb_cache(callback: CallbackQuery, user: User, repo: Repository) -> None:
    deleted = await repo.cache_cleanup(days=0)
    await answer_callback(callback, i18n.get(user.language, "admin.cache_cleared", count=deleted))


@router.callback_query(F.data == "adm:broadcast")
async def cb_broadcast(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    global _cancel
    _cancel = False
    await state.set_state(AdminStates.broadcast)
    if callback.message is not None:
        await safe_edit(
            callback.message,
            i18n.get(user.language, "admin.broadcast_prompt"),
            cancel_broadcast(user.language),
        )
    await answer_callback(callback)


@router.message(AdminStates.broadcast, Command("cancel"))
async def cmd_cancel_broadcast(message: Message, user: User, state: FSMContext) -> None:
    await state.clear()
    await message.answer(i18n.get(user.language, "admin.broadcast_cancelled"))


@router.message(AdminStates.broadcast)
async def on_broadcast_message(
    message: Message,
    user: User,
    state: FSMContext,
    repo: Repository,
) -> None:
    if message.text and message.text.startswith("/"):
        return
    users = await repo.all_user_ids(include_banned=False)
    if not users:
        await message.answer(i18n.get(user.language, "admin.broadcast_empty"))
        return
    await state.update_data(
        bcast_chat=message.chat.id,
        bcast_message=message.message_id,
        bcast_total=len(users),
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.get(user.language, "admin.broadcast_confirm"), callback_data="adm:bcast_start"
                )
            ],
            [InlineKeyboardButton(text=i18n.get(user.language, "buttons.cancel"), callback_data="adm:bcast_cancel")],
        ]
    )
    await message.answer(
        i18n.get(user.language, "admin.broadcast_preview", count=len(users)),
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "adm:bcast_start")
async def cb_broadcast_start(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    bot: Bot,
    repo: Repository,
) -> None:
    global _running, _cancel
    if _running:
        await answer_callback(callback, i18n.get(user.language, "admin.broadcast_started"), alert=True)
        return
    data = await state.get_data()
    chat_id = data.get("bcast_chat")
    message_id = data.get("bcast_message")
    if not chat_id or not message_id or callback.message is None:
        await answer_callback(callback, i18n.get(user.language, "admin.broadcast_empty"), alert=True)
        return
    await state.clear()
    _running = True
    _cancel = False
    await answer_callback(callback, i18n.get(user.language, "admin.broadcast_started"))
    asyncio.create_task(
        _run_broadcast(
            bot,
            repo,
            user,
            callback.message,
            int(chat_id),
            int(message_id),
        ),
        name="broadcast",
    )


@router.callback_query(F.data == "adm:bcast_cancel")
async def cb_broadcast_cancel(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    global _cancel
    _cancel = True
    await state.clear()
    await answer_callback(callback, i18n.get(user.language, "admin.broadcast_cancelled"))
    if callback.message is not None:
        await safe_edit(callback.message, _panel(user.language), admin_menu(user.language, False))


async def _run_broadcast(
    bot: Bot,
    repo: Repository,
    admin: User,
    status: Message,
    from_chat_id: int,
    message_id: int,
) -> None:
    global _running, _cancel
    lang = admin.language
    users = await repo.all_user_ids(include_banned=False)
    total = len(users)
    sent = failed = 0
    last_update = 0.0
    started = now_ts()
    try:
        for index, user_id in enumerate(users, start=1):
            if _cancel:
                break
            try:
                await bot.copy_message(chat_id=user_id, from_chat_id=from_chat_id, message_id=message_id)
                sent += 1
            except Exception:
                failed += 1
            if index % 40 == 0 or (asyncio.get_running_loop().time() - last_update) > 2.5:
                last_update = asyncio.get_running_loop().time()
                with contextlib.suppress(Exception):
                    await safe_edit(
                        status,
                        i18n.get(
                            lang,
                            "admin.broadcast_progress",
                            sent=sent,
                            failed=failed,
                            done=index,
                            total=total,
                        ),
                    )
            await asyncio.sleep(0.05)
        if _cancel:
            text = i18n.get(lang, "admin.broadcast_cancelled")
        else:
            text = i18n.get(lang, "admin.broadcast_done", sent=sent, failed=failed)
        with contextlib.suppress(Exception):
            await safe_edit(status, text, admin_back(lang))
        log.info("broadcast finished admin=%s sent=%s failed=%s in %ss", admin.id, sent, failed, now_ts() - started)
    finally:
        _running = False
        _cancel = False


@router.callback_query(F.data == "adm:users")
async def cb_users(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await state.set_state(AdminStates.user_lookup)
    if callback.message is not None:
        await safe_edit(
            callback.message,
            i18n.get(user.language, "admin.users_prompt"),
            admin_back(user.language),
        )
    await answer_callback(callback)


@router.message(AdminStates.user_lookup, F.text)
async def on_user_lookup(message: Message, user: User, state: FSMContext, repo: Repository, cfg: Settings) -> None:
    query = (message.text or "").strip()
    if not query:
        return
    target: User | None = None
    if query.lstrip("@").isdigit():
        target = await repo.get_user(int(query.lstrip("@")))
    if target is None:
        found = await repo.search_users(query, limit=1)
        target = found[0] if found else None
    if target is None:
        await message.answer(i18n.get(user.language, "admin.user_not_found"))
        return
    await state.clear()
    await message.answer(
        _user_info(user.language, target, cfg.free_downloads_per_day),
        reply_markup=user_actions(
            user.language,
            target.id,
            banned=target.is_banned,
            premium=target.is_premium,
        ),
    )
    await state.update_data(admin_target=target.id)


@router.callback_query(F.data.startswith("adm:grant:"))
@router.callback_query(F.data.startswith("adm:revoke:"))
@router.callback_query(F.data.startswith("adm:ban:"))
@router.callback_query(F.data.startswith("adm:unban:"))
async def cb_user_action(
    callback: CallbackQuery,
    user: User,
    repo: Repository,
    bot: Bot,
    cfg: Settings,
) -> None:
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3 or not parts[2].isdigit():
        await answer_callback(callback)
        return
    action, target_id = parts[1], int(parts[2])
    lang = user.language
    if action == "grant":
        await repo.grant_premium(target_id, 30)
        with contextlib.suppress(Exception):
            await bot.send_message(target_id, i18n.get(lang, "premium.granted", days=30))
        notice = i18n.get(lang, "admin.granted")
    elif action == "revoke":
        await repo.revoke_premium(target_id)
        notice = i18n.get(lang, "admin.revoked")
    elif action == "ban":
        await repo.set_ban(target_id, True, "banned by admin")
        notice = i18n.get(lang, "admin.banned")
    elif action == "unban":
        await repo.set_ban(target_id, False)
        notice = i18n.get(lang, "admin.unbanned")
    else:
        await answer_callback(callback)
        return
    target = await repo.get_user(target_id)
    if callback.message is not None and target is not None:
        await safe_edit(
            callback.message,
            _user_info(lang, target, cfg.free_downloads_per_day),
            user_actions(lang, target.id, banned=target.is_banned, premium=target.is_premium),
        )
    await answer_callback(callback, notice)


@router.callback_query(F.data == "adm:back")
async def cb_admin_back(callback: CallbackQuery, user: User, repo: Repository) -> None:
    if callback.message is not None:
        maintenance = await repo.get_bool_setting("maintenance", False)
        await safe_edit(callback.message, _panel(user.language), admin_menu(user.language, maintenance))
    await answer_callback(callback)


@router.message(Command("stats"))
async def cmd_stats(
    message: Message,
    user: User,
    repo: Repository,
    manager: DownloadManager,
    started_at: float,
) -> None:
    stats = await repo.stats()
    top = (
        "\n".join(
            f"• {platform_name(code)[1]} {platform_name(code)[0]} — {count}" for code, count in stats["top_platforms"]
        )
        or "—"
    )
    await message.answer(
        i18n.get(
            user.language,
            "admin.stats_body",
            users=stats["users_total"],
            today=stats["users_today"],
            week=stats["users_week"],
            premium=stats["premium"],
            banned=stats["banned"],
            d_today=stats["downloads_today"],
            done=stats["downloads_done_today"],
            failed=stats["downloads_failed_today"],
            d_total=stats["downloads_total"],
            bytes=human_bytes(stats["downloads_bytes"]),
            ai_today=stats["ai_today"],
            ai_total=stats["ai_total"],
            cache=stats["cache_count"],
            hits=stats["cache_hits"],
            avg=f"{stats['avg_download_ms'] / 1000:.1f}s",
            jobs=manager.active_count,
            uptime=human_uptime(max(0, now_ts() - started_at)),
            top=top,
        ),
        reply_markup=admin_back(user.language),
    )


@router.message(Command("grant", "revoke", "ban", "unban"))
async def cmd_moderation(
    message: Message,
    command,
    user: User,
    repo: Repository,
    bot: Bot,
) -> None:
    args = (command.args or "").split()
    if not args or not args[0].lstrip("@").isdigit():
        await message.answer(f"Usage: /{command.command} <user_id>")
        return
    target_id = int(args[0].lstrip("@"))
    action = command.command
    if action == "grant":
        days = int(args[1]) if len(args) > 1 and args[1].isdigit() else 30
        await repo.grant_premium(target_id, days)
        with contextlib.suppress(Exception):
            await bot.send_message(target_id, i18n.get(user.language, "premium.granted", days=days))
        notice = i18n.get(user.language, "admin.granted")
    elif action == "revoke":
        await repo.revoke_premium(target_id)
        notice = i18n.get(user.language, "admin.revoked")
    elif action == "ban":
        await repo.set_ban(target_id, True, "banned by admin")
        notice = i18n.get(user.language, "admin.banned")
    else:
        await repo.set_ban(target_id, False)
        notice = i18n.get(user.language, "admin.unbanned")
    await message.answer(notice)


@router.callback_query(F.data == "adm:back_main")
async def cb_admin_main(callback: CallbackQuery, user: User, is_admin: bool) -> None:
    if callback.message is not None:
        await safe_edit(
            callback.message, i18n.get(user.language, "menu.title"), main_menu(user.language, is_admin=is_admin)
        )
    await answer_callback(callback)


def _user_info(lang: str, target: User, free_limit: int = 25) -> str:
    status = i18n.get(lang, "admin.status_banned" if target.is_banned else "admin.status_active")
    plan = i18n.get(lang, "account.plan_premium" if target.is_premium else "account.plan_free")
    username = f"@{target.username}" if target.username else "—"
    limit = "∞" if target.is_premium else str(free_limit)
    ban_reason = f"⛔️ {esc(target.ban_reason)}" if target.ban_reason else ""
    return i18n.get(
        lang,
        "admin.user_info",
        name=esc(target.display_name),
        id=target.id,
        username=username,
        status=status,
        plan=plan,
        date=fmt_date(target.created_at),
        seen=fmt_date(target.last_seen, with_time=True),
        d_today=target.downloads_today,
        limit=limit,
        d_total=target.downloads_total,
        ai_today=target.ai_today,
        ai_total=target.ai_total,
        refs=target.referral_count,
        ban_reason=ban_reason,
    )


@router.message(Command("uptime"))
async def cmd_uptime(message: Message, started_at: float) -> None:
    started = datetime.fromtimestamp(started_at, tz=timezone.utc)
    await message.answer(f"⬆️ Up since {started:%Y-%m-%d %H:%M} UTC\n⏱ {human_uptime(max(0, now_ts() - started_at))}")
