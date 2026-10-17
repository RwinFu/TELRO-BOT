from __future__ import annotations

import pytest

from bot.utils.time import today_key


@pytest.mark.asyncio
async def test_user_lifecycle(repo):
    user = await repo.upsert_user(10, "alice", "Alice", language="fa")
    assert user.id == 10
    assert user.referral_count == 0
    assert user.pref_quality == "ask"
    assert not user.is_premium

    again = await repo.upsert_user(10, "alice2", "Alice B")
    assert again.username == "alice2"

    await repo.set_language(10, "en")
    await repo.set_pref(10, "pref_quality", "1080")
    await repo.set_pref(10, "pref_caption", 0)
    fresh = await repo.get_user(10)
    assert fresh.language == "en"
    assert fresh.pref_quality == "1080"
    assert fresh.pref_caption is False

    with pytest.raises(ValueError):
        await repo.set_pref(10, "is_banned", 1)


@pytest.mark.asyncio
async def test_daily_quota_and_refund(repo):
    await repo.upsert_user(11, None, "Bob")
    allowed, used = await repo.consume_download(11, 2)
    assert allowed and used == 1
    allowed, used = await repo.consume_download(11, 2)
    assert allowed and used == 2
    allowed, used = await repo.consume_download(11, 2)
    assert not allowed and used == 2

    await repo.refund_download(11)
    allowed, used = await repo.consume_download(11, 2)
    assert allowed and used == 2

    allowed, used = await repo.consume_ai(11, 1)
    assert allowed and used == 1
    allowed, _ = await repo.consume_ai(11, 1)
    assert not allowed
    await repo.refund_ai(11)
    allowed, _ = await repo.consume_ai(11, 1)
    assert allowed


@pytest.mark.asyncio
async def test_daily_reset(repo):
    await repo.upsert_user(12, None, "Reset")
    await repo.db.execute(
        "UPDATE users SET downloads_today = 5, ai_today = 3, usage_date = '2000-01-01' WHERE id = 12"
    )
    await repo.reset_daily(12)
    user = await repo.get_user(12)
    assert user.downloads_today == 0
    assert user.ai_today == 0
    assert user.usage_date == today_key()


@pytest.mark.asyncio
async def test_premium_and_referral(repo):
    await repo.upsert_user(1, "ref", "Referrer")
    await repo.upsert_user(2, "new", "New")
    assert await repo.set_referred_by(2, 1)

    count, reward = await repo.register_referral(1, 2, target=1, reward_days=7)
    assert count == 1
    assert reward == 7
    referrer = await repo.get_user(1)
    assert referrer.referral_count == 1
    assert referrer.is_premium
    assert referrer.premium_until is not None

    await repo.revoke_premium(1)
    assert not (await repo.get_user(1)).is_premium

    until = await repo.grant_premium(1, 30)
    assert until and until > 0
    assert (await repo.get_user(1)).is_premium


@pytest.mark.asyncio
async def test_cache(repo):
    await repo.cache_put("youtube:1:720", "video", ["file-id"], title="Video", size=1024)
    cached = await repo.cache_get("youtube:1:720")
    assert cached is not None
    assert cached.file_ids == ["file-id"]
    assert cached.kind == "video"
    assert await repo.cache_count() == 1

    await repo.cache_cleanup(days=0)
    assert await repo.cache_get("youtube:1:720") is None


@pytest.mark.asyncio
async def test_ai_history(repo):
    await repo.upsert_user(5, None, "AI")
    for index in range(45):
        await repo.ai_add(5, "user" if index % 2 == 0 else "assistant", f"msg-{index}")
    history = await repo.ai_history(5, limit=5)
    assert len(history) == 5
    assert history[-1] == ("user", "msg-44")
    assert await repo.ai_count(5) == 40
    await repo.ai_clear(5)
    assert await repo.ai_count(5) == 0


@pytest.mark.asyncio
async def test_pending_and_deep_links(repo):
    token = await repo.pending_create("media", user_id=1, url="https://x", payload={"a": 1})
    pending = await repo.pending_get(token)
    assert pending is not None
    assert pending["payload"] == {"a": 1}
    await repo.pending_delete(token)
    assert await repo.pending_get(token) is None

    deep = await repo.deep_link_create(1, "https://youtube.com/watch?v=x")
    assert await repo.deep_link_take(deep) == "https://youtube.com/watch?v=x"
    assert await repo.deep_link_take(deep) is None


@pytest.mark.asyncio
async def test_settings_and_counters(repo):
    assert await repo.get_bool_setting("maintenance", False) is False
    await repo.set_setting("maintenance", "1")
    assert await repo.get_bool_setting("maintenance") is True
    assert await repo.get_int_setting("unknown", 7) == 7
    await repo.bump_counter("cache_hits", 2)
    assert await repo.get_counter("cache_hits") == 2


@pytest.mark.asyncio
async def test_stats(repo):
    await repo.upsert_user(1, None, "A")
    await repo.upsert_user(2, None, "B")
    download_id = await repo.log_download(1, "https://x", "youtube", "Title", "720")
    await repo.finish_download(download_id, "done", size=1000, duration=60, elapsed_ms=1200)
    failed = await repo.log_download(2, "https://y", "tiktok", "T", "best")
    await repo.finish_download(failed, "failed", error="boom")

    stats = await repo.stats()
    assert stats["users_total"] == 2
    assert stats["downloads_total"] == 2
    assert stats["downloads_done_today"] == 1
    assert stats["downloads_failed_today"] == 1
    assert stats["downloads_bytes"] == 1000
    assert ("youtube", 1) in stats["top_platforms"]


@pytest.mark.asyncio
async def test_ban(repo):
    await repo.upsert_user(7, None, "Bad")
    assert await repo.set_ban(7, True, "spam")
    user = await repo.get_user(7)
    assert user.is_banned
    assert user.ban_reason == "spam"
    await repo.set_ban(7, False)
    assert not (await repo.get_user(7)).is_banned
