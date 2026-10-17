"""Shared view builders used by several handlers."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.constants import PLATFORMS
from bot.db.repository import User
from bot.i18n import i18n
from bot.utils.formatting import human_duration, progress_bar
from bot.utils.telegram import safe_edit
from bot.utils.text import esc
from bot.utils.time import fmt_date, fmt_remaining

POPULAR_PLATFORMS = ("youtube", "instagram", "tiktok", "twitter", "facebook", "reddit", "soundcloud", "pinterest")


def platform_list() -> str:
    lines = []
    for code in POPULAR_PLATFORMS:
        platform = next((item for item in PLATFORMS if item.code == code), None)
        if platform:
            lines.append(f"{platform.emoji} {platform.name}")
    return " · ".join(lines)


def limit_for(cfg: Settings, user: User) -> str:
    return (
        i18n.get(user.language, "account.unlimited")
        if user.is_premium or user.id in cfg.admins
        else str(cfg.free_downloads_per_day)
    )


def ai_limit_for(cfg: Settings, user: User) -> str:
    return (
        i18n.get(user.language, "account.unlimited")
        if user.is_premium or user.id in cfg.admins
        else str(cfg.free_ai_per_day)
    )


def welcome_text(cfg: Settings, user: User) -> str:
    lang = user.language
    return "\n\n".join(
        [
            i18n.get(lang, "welcome.title"),
            i18n.get(lang, "welcome.body", name=esc(user.first_name or "friend")),
            i18n.get(lang, "welcome.bullets"),
            i18n.get(lang, "welcome.stats", downloads=user.downloads_total, limit=limit_for(cfg, user)),
            i18n.get(lang, "welcome.hint"),
        ]
    )


def menu_text(user: User) -> str:
    lang = user.language
    plan = i18n.get(lang, "account.plan_premium" if user.is_premium else "account.plan_free")
    return f"{i18n.get(lang, 'menu.title')}\n{i18n.get(lang, 'menu.subtitle')}\n\n💎 {plan}"


def account_text(cfg: Settings, user: User) -> str:
    lang = user.language
    expiry = ""
    if user.is_premium and user.premium_until:
        expiry = i18n.get(
            lang,
            "account.expires",
            date=fmt_date(user.premium_until),
            remaining=fmt_remaining(user.premium_until),
        )
    plan = i18n.get(lang, "account.plan_premium" if user.is_premium else "account.plan_free")
    text = i18n.get(
        lang,
        "account.body",
        name=esc(user.first_name or str(user.id)),
        id=user.id,
        plan=plan,
        expiry=expiry,
        used=user.downloads_today,
        limit=limit_for(cfg, user),
        ai_used=user.ai_today,
        ai_limit=ai_limit_for(cfg, user),
        total=user.downloads_total,
        refs=user.referral_count,
        date=fmt_date(user.created_at),
    )
    if not user.is_premium:
        text += "\n\n" + i18n.get(lang, "account.upgrade")
    return text


def settings_text(user: User) -> str:
    lang = user.language
    return f"{i18n.get(lang, 'settings.title')}\n\n{i18n.get(lang, 'settings.body')}"


def help_text(cfg: Settings, user: User) -> str:
    lang = user.language
    support = ""
    if cfg.support_username:
        support = f"\n\n{i18n.get(lang, 'help.support', support='@' + cfg.support_username.lstrip('@'))}"
    return (
        "\n\n".join(
            [
                i18n.get(lang, "help.title"),
                i18n.get(lang, "help.body"),
                i18n.get(lang, "help.commands"),
                i18n.get(lang, "help.tips"),
            ]
        )
        + support
    )


def invite_text(cfg: Settings, user: User, link: str | None) -> str:
    lang = user.language
    if not link:
        return f"{i18n.get(lang, 'invite.title')}\n\n{i18n.get(lang, 'invite.no_username')}"
    count = user.referral_count
    target = max(1, cfg.referral_target)
    bar = progress_bar(count % target / target * 100, width=8)
    return i18n.get(
        lang,
        "invite.body",
        link=esc(link),
        count=count,
        target=target,
        days=cfg.referral_reward_days,
        bar=bar,
    )


def premium_text(cfg: Settings, user: User) -> str:
    lang = user.language
    text = f"{i18n.get(lang, 'premium.title')}\n\n{i18n.get(lang, 'premium.body')}"
    if user.is_premium and user.premium_until:
        text = i18n.get(
            lang,
            "premium.active",
            remaining=f" ({fmt_remaining(user.premium_until)})",
        )
    if not cfg.support_username:
        text += f"\n\n{i18n.get(lang, 'premium.no_support')}"
    return text


async def show_screen(
    message: Message | None,
    text: str,
    keyboard: InlineKeyboardMarkup,
    *,
    edit: bool = False,
) -> None:
    """Send or edit a screen without raising if the message is gone."""
    if message is None:
        return
    if edit:
        if await safe_edit(message, text, keyboard):
            return
    from aiogram.types import LinkPreviewOptions

    try:
        await message.answer(text, reply_markup=keyboard, link_preview_options=LinkPreviewOptions(is_disabled=True))
    except Exception:  # pragma: no cover - best effort UI
        pass


def human_uptime(seconds: float) -> str:
    return human_duration(int(seconds))
