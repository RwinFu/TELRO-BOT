"""Inline keyboard builders (callback data is kept under 64 bytes)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import Settings
from bot.db.repository import User
from bot.i18n import i18n
from bot.services.downloader.formats import MediaInfo
from bot.services.downloader.inspector import SearchResult
from bot.utils.formatting import human_duration, truncate


def _button(text: str, data: str | None = None, url: str | None = None) -> InlineKeyboardButton:
    if url:
        return InlineKeyboardButton(text=text, url=url)
    return InlineKeyboardButton(text=text, callback_data=data or "noop")


def main_menu(lang: str, *, is_admin: bool = False) -> InlineKeyboardMarkup:
    t = lambda key: i18n.get(lang, key)  # noqa: E731
    rows = [
        [_button(t("buttons.download"), "menu:download"), _button(t("buttons.music"), "menu:music")],
        [_button(t("buttons.ai"), "menu:ai"), _button(t("buttons.image"), "menu:image")],
        [_button(t("buttons.premium"), "menu:premium"), _button(t("buttons.account"), "menu:account")],
        [_button(t("buttons.invite"), "menu:invite"), _button(t("buttons.settings"), "menu:settings")],
        [_button(t("buttons.help"), "menu:help")],
    ]
    if is_admin:
        rows.append([_button(t("buttons.admin"), "menu:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_menu(lang: str, *, show_admin: bool = False) -> InlineKeyboardMarkup:
    row = [_button(i18n.get(lang, "buttons.menu"), "menu:main")]
    if show_admin:
        row.append(_button(i18n.get(lang, "buttons.admin"), "menu:admin"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def quality_keyboard(lang: str, media: MediaInfo, token: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    best = media.best
    if best is not None:
        rows.append([_button(i18n.get(lang, "download.best_button", label=best.label), f"q:{token}:best")])
    video_options = [option for option in media.qualities if not option.is_audio]
    current_row: list[InlineKeyboardButton] = []
    for option in video_options:
        current_row.append(_button(option.button_text, f"q:{token}:{option.callback_value}"))
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    audio = next((option for option in media.qualities if option.is_audio), None)
    if audio is not None:
        rows.append([_button(audio.button_text, f"q:{token}:audio")])
    rows.append(
        [
            _button(i18n.get(lang, "buttons.share"), f"share:{token}"),
            _button(i18n.get(lang, "buttons.cancel"), "menu:main"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def playlist_keyboard(lang: str, token: str, count: int) -> InlineKeyboardMarkup:
    limit = min(count, 10)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(i18n.get(lang, "download.playlist_first"), f"pl:{token}:first")],
            [_button(i18n.get(lang, "download.playlist_all", count=limit), f"pl:{token}:all")],
            [
                _button(i18n.get(lang, "buttons.share"), f"share:{token}"),
                _button(i18n.get(lang, "buttons.cancel"), "menu:main"),
            ],
        ]
    )


def music_results(lang: str, token: str, results: list[SearchResult]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, result in enumerate(results):
        duration = human_duration(result.duration) if result.duration else ""
        title = truncate(result.title, 48)
        label = f"{index + 1}. {title}" + (f" · {duration}" if duration else "")
        rows.append([_button(label, f"m:{token}:{index}")])
    rows.append([_button(i18n.get(lang, "buttons.search_again"), "menu:music")])
    rows.append([_button(i18n.get(lang, "buttons.cancel"), "menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def aspect_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button(i18n.get(lang, "image.square"), "img:aspect:square"),
                _button(i18n.get(lang, "image.landscape"), "img:aspect:landscape"),
            ],
            [
                _button(i18n.get(lang, "image.portrait"), "img:aspect:portrait"),
                _button(i18n.get(lang, "image.story"), "img:aspect:story"),
            ],
            [_button(i18n.get(lang, "buttons.cancel"), "menu:main")],
        ]
    )


def image_result(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button(i18n.get(lang, "buttons.again"), "img:again"),
                _button(i18n.get(lang, "buttons.new_image"), "img:new"),
            ],
            [_button(i18n.get(lang, "buttons.menu"), "menu:main")],
        ]
    )


def settings_keyboard(lang: str, user: User) -> InlineKeyboardMarkup:
    quality_values = ("ask", "best", "1080", "720", "480", "360")
    quality_row: list[InlineKeyboardButton] = []
    quality_rows: list[list[InlineKeyboardButton]] = []
    for value in quality_values:
        label = i18n.get(lang, "settings.ask") if value == "ask" else value
        mark = "✅ " if user.pref_quality == value else ""
        quality_row.append(_button(f"{mark}{label}", f"set:quality:{value}"))
        if len(quality_row) == 3:
            quality_rows.append(quality_row)
            quality_row = []
    if quality_row:
        quality_rows.append(quality_row)

    lang_row = [
        _button(f"{'✅ ' if user.language == 'fa' else ''}🇮🇷 فارسی", "set:lang:fa"),
        _button(f"{'✅ ' if user.language == 'en' else ''}🇬🇧 English", "set:lang:en"),
    ]
    audio_row = [
        _button(f"{'✅ ' if user.pref_audio == 'mp3' else ''}MP3", "set:audio:mp3"),
        _button(f"{'✅ ' if user.pref_audio == 'm4a' else ''}M4A", "set:audio:m4a"),
    ]
    caption_row = [
        _button(
            f"{'✅ ' if user.pref_caption else ''}{i18n.get(lang, 'settings.caption_on')}",
            "set:caption:1",
        ),
        _button(
            f"{'✅ ' if not user.pref_caption else ''}{i18n.get(lang, 'settings.caption_off')}",
            "set:caption:0",
        ),
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            lang_row,
            *quality_rows,
            audio_row,
            caption_row,
            [_button(i18n.get(lang, "settings.clear_ai"), "set:clear_ai")],
            [_button(i18n.get(lang, "buttons.menu"), "menu:main")],
        ]
    )


def account_keyboard(lang: str, *, premium: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if not premium:
        rows.append([_button(i18n.get(lang, "buttons.premium"), "menu:premium")])
    rows.append([_button(i18n.get(lang, "buttons.invite"), "menu:invite")])
    rows.append([_button(i18n.get(lang, "buttons.menu"), "menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def invite_keyboard(lang: str, link: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if link:
        share = f"https://t.me/share/url?url={link}&text={i18n.get(lang, 'invite.share_text')}"
        rows.append([_button(i18n.get(lang, "invite.copy"), url=link)])
        rows.append([_button(i18n.get(lang, "invite.share"), url=share)])
    rows.append([_button(i18n.get(lang, "buttons.menu"), "menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def premium_keyboard(lang: str, support_url: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if support_url:
        rows.append([_button(i18n.get(lang, "premium.contact"), url=support_url)])
    rows.append([_button(i18n.get(lang, "buttons.menu"), "menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def join_keyboard(lang: str, channels: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, channel in enumerate(channels):
        if channel.startswith("http"):
            url = channel
        else:
            url = f"https://t.me/{channel.lstrip('@')}"
        rows.append([_button(i18n.get(lang, "join.button", n=index + 1), url=url)])
    rows.append([_button(i18n.get(lang, "buttons.check_join"), "join:check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def force_join_required(lang: str, channels: list[str]) -> InlineKeyboardMarkup:
    return join_keyboard(lang, channels)


def admin_menu(lang: str, maintenance: bool) -> InlineKeyboardMarkup:
    maintenance_text = (
        i18n.get(lang, "admin.maintenance_off") if maintenance else i18n.get(lang, "admin.maintenance_on")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(i18n.get(lang, "admin.stats"), "adm:stats")],
            [_button(i18n.get(lang, "admin.broadcast"), "adm:broadcast")],
            [_button(i18n.get(lang, "admin.users"), "adm:users")],
            [_button(maintenance_text, "adm:maintenance")],
            [_button(i18n.get(lang, "admin.cache"), "adm:cache")],
            [_button(i18n.get(lang, "buttons.menu"), "menu:main")],
        ]
    )


def admin_back(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(i18n.get(lang, "buttons.back"), "menu:admin")],
            [_button(i18n.get(lang, "buttons.menu"), "menu:main")],
        ]
    )


def cancel_broadcast(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_button(i18n.get(lang, "buttons.cancel"), "adm:bcast_cancel")]])


def user_actions(lang: str, user_id: int, *, banned: bool, premium: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if premium:
        rows.append([_button(i18n.get(lang, "admin.revoke"), f"adm:revoke:{user_id}")])
    else:
        rows.append([_button(i18n.get(lang, "admin.grant"), f"adm:grant:{user_id}")])
    if banned:
        rows.append([_button(i18n.get(lang, "admin.unban"), f"adm:unban:{user_id}")])
    else:
        rows.append([_button(i18n.get(lang, "admin.ban"), f"adm:ban:{user_id}")])
    rows.append([_button(i18n.get(lang, "buttons.back"), "adm:users")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ai_mode(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(i18n.get(lang, "buttons.new_chat"), "ai:reset"), _button(i18n.get(lang, "ai.exit"), "ai:exit")],
            [_button(i18n.get(lang, "buttons.menu"), "menu:main")],
        ]
    )


def simple_back(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_button(i18n.get(lang, "buttons.menu"), "menu:main")]])


def support_url(cfg: Settings) -> str | None:
    username = (cfg.support_username or "").strip().lstrip("@")
    return f"https://t.me/{username}" if username else None
