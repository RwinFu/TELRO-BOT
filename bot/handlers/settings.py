"""Settings, account, premium, invites and the help screen."""

from __future__ import annotations

import contextlib
import logging

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.db.repository import Repository, User
from bot.handlers.common import (
    account_text,
    help_text,
    invite_text,
    menu_text,
    premium_text,
    settings_text,
)
from bot.i18n import i18n
from bot.keyboards.inline import (
    account_keyboard,
    back_menu,
    invite_keyboard,
    main_menu,
    premium_keyboard,
    settings_keyboard,
    support_url,
)
from bot.utils.telegram import answer_callback, safe_edit

log = logging.getLogger(__name__)
router = Router(name="settings")

QUALITY_VALUES = {"ask", "best", "1080", "720", "480", "360", "2160", "1440"}
AUDIO_VALUES = {"mp3", "m4a"}


async def _reload(repo: Repository, user: User) -> User:
    fresh = await repo.get_user(user.id)
    return fresh or user


@router.message(Command("settings"))
async def cmd_settings(message: Message, user: User) -> None:
    await message.answer(settings_text(user), reply_markup=settings_keyboard(user.language, user))


@router.message(Command("account"))
async def cmd_account(message: Message, user: User, cfg: Settings) -> None:
    await message.answer(
        account_text(cfg, user), reply_markup=account_keyboard(user.language, premium=user.is_premium)
    )


@router.message(Command("premium"))
async def cmd_premium(message: Message, user: User, cfg: Settings) -> None:
    await message.answer(
        premium_text(cfg, user),
        reply_markup=premium_keyboard(user.language, support_url(cfg)),
        link_preview_options={"is_disabled": True},
    )


@router.message(Command("invite"))
async def cmd_invite(message: Message, user: User, cfg: Settings) -> None:
    link = f"https://t.me/{cfg.bot_username}?start=ref_{user.id}" if cfg.bot_username else None
    await message.answer(
        invite_text(cfg, user, link),
        reply_markup=invite_keyboard(user.language, link),
        link_preview_options={"is_disabled": True},
    )


@router.callback_query(lambda event: event.data == "menu:settings")
async def cb_settings(callback: CallbackQuery, user: User) -> None:
    await _show(callback, settings_text(user), settings_keyboard(user.language, user))


@router.callback_query(lambda event: event.data == "menu:account")
async def cb_account(callback: CallbackQuery, user: User, cfg: Settings) -> None:
    await _show(
        callback,
        account_text(cfg, user),
        account_keyboard(user.language, premium=user.is_premium),
    )


@router.callback_query(lambda event: event.data == "menu:premium")
async def cb_premium(callback: CallbackQuery, user: User, cfg: Settings) -> None:
    await _show(
        callback,
        premium_text(cfg, user),
        premium_keyboard(user.language, support_url(cfg)),
    )


@router.callback_query(lambda event: event.data == "menu:invite")
async def cb_invite(callback: CallbackQuery, user: User, cfg: Settings) -> None:
    link = f"https://t.me/{cfg.bot_username}?start=ref_{user.id}" if cfg.bot_username else None
    await _show(callback, invite_text(cfg, user, link), invite_keyboard(user.language, link))


@router.callback_query(lambda event: event.data == "menu:help")
async def cb_help(callback: CallbackQuery, user: User, cfg: Settings) -> None:
    await _show(callback, help_text(cfg, user), back_menu(user.language))


@router.callback_query(lambda event: event.data and event.data.startswith("set:"))
async def cb_set(
    callback: CallbackQuery,
    user: User,
    repo: Repository,
    state: FSMContext,
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) < 2:
        await answer_callback(callback)
        return
    action = parts[1]
    value = parts[2] if len(parts) > 2 else ""
    if action == "lang" and value in {"fa", "en"}:
        await repo.set_language(user.id, value)
        user = await _reload(repo, user)
    elif action == "quality" and value in QUALITY_VALUES:
        await repo.set_pref(user.id, "pref_quality", value)
        user = await _reload(repo, user)
    elif action == "audio" and value in AUDIO_VALUES:
        await repo.set_pref(user.id, "pref_audio", value)
        user = await _reload(repo, user)
    elif action == "caption" and value in {"0", "1"}:
        await repo.set_pref(user.id, "pref_caption", int(value))
        user = await _reload(repo, user)
    elif action == "clear_ai":
        await repo.ai_clear(user.id)
        await answer_callback(callback, i18n.get(user.language, "settings.ai_cleared"))
        return
    else:
        await answer_callback(callback)
        return
    with contextlib.suppress(Exception):
        await callback.answer(i18n.get(user.language, "settings.saved"))
    if callback.message is not None:
        await safe_edit(
            callback.message,
            settings_text(user),
            settings_keyboard(user.language, user),
        )


@router.callback_query(lambda event: event.data == "join:check")
async def cb_join_check(callback: CallbackQuery, user: User, cfg: Settings, bot: Bot) -> None:
    if not cfg.join_channels:
        await _show(callback, menu_text(user), main_menu(user.language))
        return
    missing: list[str] = []
    for channel in cfg.join_channels:
        try:
            member = await bot.get_chat_member(channel, user.id)
            status = str(getattr(member, "status", ""))
            if status not in {
                "ChatMemberStatus.MEMBER",
                "ChatMemberStatus.ADMINISTRATOR",
                "ChatMemberStatus.CREATOR",
                "member",
                "administrator",
                "creator",
            }:
                missing.append(channel)
        except Exception:
            # Don't lock users out because of a configuration or network error.
            log.warning("join check failed for %s", channel)
            continue
    if missing:
        await answer_callback(callback, i18n.get(user.language, "join.not_member"), alert=True)
        return
    await answer_callback(callback, i18n.get(user.language, "join.done"))
    if callback.message is not None:
        await safe_edit(callback.message, menu_text(user), main_menu(user.language))


@router.callback_query(lambda event: event.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await answer_callback(callback)


async def _show(callback: CallbackQuery, text: str, keyboard) -> None:
    if callback.message is not None:
        await safe_edit(callback.message, text, keyboard)
    await answer_callback(callback)
