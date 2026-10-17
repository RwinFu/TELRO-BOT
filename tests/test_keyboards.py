from __future__ import annotations

from bot.db.repository import User
from bot.keyboards.inline import (
    account_keyboard,
    admin_back,
    admin_menu,
    ai_mode,
    aspect_keyboard,
    back_menu,
    cancel_broadcast,
    force_join_required,
    image_result,
    invite_keyboard,
    main_menu,
    music_results,
    playlist_keyboard,
    premium_keyboard,
    quality_keyboard,
    settings_keyboard,
    simple_back,
    user_actions,
)
from bot.services.downloader.formats import MediaInfo, QualityOption
from bot.services.downloader.inspector import SearchResult


def make_user() -> User:
    return User(
        id=123456789,
        username="tester",
        first_name="Tester",
        language="fa",
        created_at=0,
        last_seen=0,
        premium_until=None,
        is_banned=False,
        ban_reason=None,
        downloads_today=2,
        ai_today=3,
        usage_date="2026-01-01",
        downloads_total=10,
        ai_total=20,
        referred_by=None,
        referral_count=4,
        pref_quality="1080",
        pref_audio="mp3",
        pref_caption=True,
    )


def media() -> MediaInfo:
    return MediaInfo(
        url="https://youtube.com/watch?v=abcdef",
        platform="youtube",
        media_id="abcdef",
        title="A very nice video",
        qualities=[
            QualityOption(2160, "4K", 900_000_000),
            QualityOption(1080, "FHD", 50_000_000),
            QualityOption(720, "HD", 25_000_000),
            QualityOption(0, "MP3", 5_000_000, is_audio=True),
        ],
    )


def markups():
    user = make_user()
    results = [
        SearchResult("Song one", "https://youtube.com/watch?v=1", 200, "Artist", None, "1"),
        SearchResult("Song two with a very long name " * 3, "https://youtube.com/watch?v=2", 0, "", None, "2"),
    ]
    return [
        main_menu("fa", is_admin=True),
        main_menu("en"),
        back_menu("fa"),
        simple_back("fa"),
        quality_keyboard("fa", media(), "abc123456789"),
        playlist_keyboard("fa", "abc123456789", 25),
        music_results("fa", "abc123456789", results),
        aspect_keyboard("fa"),
        image_result("fa"),
        settings_keyboard("fa", user),
        account_keyboard("fa", premium=False),
        account_keyboard("fa", premium=True),
        invite_keyboard("fa", "https://t.me/Rwinro_bot?start=ref_1"),
        invite_keyboard("fa", None),
        premium_keyboard("fa", "https://t.me/support"),
        force_join_required("fa", ["@channel", "https://t.me/+abc"]),
        admin_menu("fa", False),
        admin_back("fa"),
        cancel_broadcast("fa"),
        user_actions("fa", 123, banned=False, premium=False),
        user_actions("fa", 123, banned=True, premium=True),
        ai_mode("fa"),
    ]


def test_callback_data_fits_telegram_limit():
    for markup in markups():
        for row in markup.inline_keyboard:
            assert row
            for button in row:
                if button.callback_data:
                    assert len(button.callback_data.encode()) <= 64
                    assert button.callback_data != ""
                assert button.text


def test_settings_keyboard_marks_current_values():
    markup = settings_keyboard("fa", make_user())
    callback_data = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert "set:quality:1080" in callback_data
    assert "set:audio:mp3" in callback_data
    assert "set:caption:1" in callback_data
    assert any(text.text.startswith("✅ 1080") for row in markup.inline_keyboard for text in row)


def test_quality_keyboard_contains_audio_and_best():
    markup = quality_keyboard("fa", media(), "token")
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert "q:token:best" in callbacks
    assert "q:token:1080" in callbacks
    assert "q:token:audio" in callbacks
