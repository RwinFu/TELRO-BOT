"""Start, welcome, deep links, main menu and basic commands."""

from __future__ import annotations

import contextlib
import logging

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.db.repository import Repository, User
from bot.handlers.common import help_text, menu_text, welcome_text
from bot.i18n import i18n
from bot.keyboards.inline import main_menu
from bot.services.downloader.direct import DirectDownloader
from bot.services.downloader.inspector import Inspector
from bot.services.downloader.manager import DownloadManager
from bot.utils.telegram import answer_callback, safe_edit
from bot.utils.text import esc
from bot.utils.time import now_ts

log = logging.getLogger(__name__)
router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    user: User,
    cfg: Settings,
    repo: Repository,
    bot: Bot,
    is_admin: bool,
    inspector: Inspector,
    direct: DirectDownloader,
    manager: DownloadManager,
) -> None:
    await state.clear()
    if message.chat.type != "private":
        username = cfg.bot_username
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🚀 Open TELRO", url=f"https://t.me/{username}?start=group")]]
        )
        await message.answer(
            f"{i18n.get(user.language, 'welcome.title')}\n\n{i18n.get(user.language, 'welcome.body', name=esc(user.first_name or 'friend'))}\n\n"
            f"<i>{i18n.get(user.language, 'help.tips')}</i>",
            reply_markup=keyboard,
            link_preview_options={"is_disabled": True},
        )
        return

    args = (command.args or "").strip()
    if args.startswith("ref_"):
        await _handle_referral(args[4:], user, cfg, repo, bot)
        fresh = await repo.get_user(user.id)
        if fresh is not None:
            user = fresh

    await message.answer(
        welcome_text(cfg, user),
        reply_markup=main_menu(user.language, is_admin=is_admin),
        link_preview_options={"is_disabled": True},
    )

    if args.startswith("dl_"):
        token = args[3:]
        url = await repo.deep_link_take(token)
        if not url:
            await message.answer(i18n.get(user.language, "deeplink.expired"))
            return
        from bot.handlers.download import begin_download

        await begin_download(
            message,
            url,
            user,
            cfg=cfg,
            repo=repo,
            bot=bot,
            inspector=inspector,
            direct=direct,
            manager=manager,
        )


@router.message(Command("menu"))
async def cmd_menu(message: Message, user: User, state: FSMContext, is_admin: bool) -> None:
    await state.clear()
    await message.answer(
        menu_text(user),
        reply_markup=main_menu(user.language, is_admin=is_admin),
        link_preview_options={"is_disabled": True},
    )


@router.message(Command("help"))
@router.message(Command("guide"))
async def cmd_help(message: Message, user: User, cfg: Settings) -> None:
    from bot.keyboards.inline import simple_back

    await message.answer(
        help_text(cfg, user),
        reply_markup=simple_back(user.language),
        link_preview_options={"is_disabled": True},
    )


@router.message(Command("exit"))
async def cmd_exit(message: Message, user: User, state: FSMContext, is_admin: bool) -> None:
    await state.clear()
    await message.answer(
        i18n.get(user.language, "ai.exit"),
        reply_markup=main_menu(user.language, is_admin=is_admin),
    )


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    if message.from_user is None:
        return
    await message.answer(f"🆔 <code>{message.from_user.id}</code>")


@router.callback_query(lambda event: event.data == "menu:main")
async def cb_main(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    is_admin: bool,
) -> None:
    await state.clear()
    if callback.message is not None:
        await safe_edit(
            callback.message,
            menu_text(user),
            main_menu(user.language, is_admin=is_admin),
        )
    await answer_callback(callback)


async def _handle_referral(
    raw_id: str,
    user: User,
    cfg: Settings,
    repo: Repository,
    bot: Bot,
) -> None:
    if not raw_id.isdigit():
        return
    referrer_id = int(raw_id)
    if referrer_id == user.id or user.referred_by is not None:
        return
    if now_ts() - user.created_at > 600:
        return
    if not await repo.set_referred_by(user.id, referrer_id):
        return
    count, reward = await repo.register_referral(
        referrer_id,
        user.id,
        target=max(1, cfg.referral_target),
        reward_days=cfg.referral_reward_days,
    )
    referrer = await repo.get_user(referrer_id)
    if referrer is None:
        return
    lang = referrer.language
    with contextlib.suppress(Exception):
        await bot.send_message(
            referrer_id,
            i18n.get(
                lang,
                "invite.joined",
                name=esc(user.first_name or "دوستت"),
                count=count,
                target=max(1, cfg.referral_target),
            ),
        )
    if reward:
        with contextlib.suppress(Exception):
            await bot.send_message(referrer_id, i18n.get(lang, "invite.reward", days=reward))
        log.info("referral reward: user=%s invited=%s count=%s days=%s", referrer_id, user.id, count, reward)
