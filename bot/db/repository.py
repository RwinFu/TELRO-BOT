"""Async SQLite storage for users, downloads, cache, AI history and settings."""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

from bot.constants import CACHE_TTL_DAYS, DEEP_LINK_TTL_SECONDS, PENDING_TTL_SECONDS
from bot.utils.time import now_ts, start_of_day_ts, today_key

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,
    username        TEXT,
    first_name      TEXT NOT NULL DEFAULT '',
    language        TEXT NOT NULL DEFAULT 'fa',
    created_at      INTEGER NOT NULL,
    last_seen       INTEGER NOT NULL,
    premium_until   INTEGER,
    is_banned       INTEGER NOT NULL DEFAULT 0,
    ban_reason      TEXT,
    downloads_today INTEGER NOT NULL DEFAULT 0,
    ai_today        INTEGER NOT NULL DEFAULT 0,
    usage_date      TEXT,
    downloads_total INTEGER NOT NULL DEFAULT 0,
    ai_total        INTEGER NOT NULL DEFAULT 0,
    referred_by     INTEGER,
    referral_count  INTEGER NOT NULL DEFAULT 0,
    pref_quality    TEXT NOT NULL DEFAULT 'ask',
    pref_audio      TEXT NOT NULL DEFAULT 'mp3',
    pref_caption    INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen);
CREATE INDEX IF NOT EXISTS idx_users_created ON users(created_at);

CREATE TABLE IF NOT EXISTS downloads (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    url        TEXT NOT NULL,
    platform   TEXT NOT NULL DEFAULT '',
    title      TEXT,
    quality    TEXT,
    status     TEXT NOT NULL DEFAULT 'started',
    size       INTEGER,
    duration   INTEGER,
    elapsed_ms INTEGER,
    error      TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_downloads_created ON downloads(created_at);
CREATE INDEX IF NOT EXISTS idx_downloads_user ON downloads(user_id);

CREATE TABLE IF NOT EXISTS file_cache (
    key        TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    file_ids   TEXT NOT NULL,
    title      TEXT,
    size       INTEGER,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cache_created ON file_cache(created_at);

CREATE TABLE IF NOT EXISTS ai_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_user ON ai_messages(user_id, id);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER,
    kind       TEXT NOT NULL,
    url        TEXT,
    payload    TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pending_created ON pending(created_at);

CREATE TABLE IF NOT EXISTS deep_links (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER,
    url        TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS counters (
    key   TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass(slots=True)
class User:
    id: int
    username: str | None
    first_name: str
    language: str
    created_at: int
    last_seen: int
    premium_until: int | None
    is_banned: bool
    ban_reason: str | None
    downloads_today: int
    ai_today: int
    usage_date: str | None
    downloads_total: int
    ai_total: int
    referred_by: int | None
    referral_count: int
    pref_quality: str
    pref_audio: str
    pref_caption: bool

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> User:
        return cls(
            id=row["id"],
            username=row["username"],
            first_name=row["first_name"] or "",
            language=row["language"] or "fa",
            created_at=row["created_at"],
            last_seen=row["last_seen"],
            premium_until=row["premium_until"],
            is_banned=bool(row["is_banned"]),
            ban_reason=row["ban_reason"],
            downloads_today=row["downloads_today"],
            ai_today=row["ai_today"],
            usage_date=row["usage_date"],
            downloads_total=row["downloads_total"],
            ai_total=row["ai_total"],
            referred_by=row["referred_by"],
            referral_count=row["referral_count"],
            pref_quality=row["pref_quality"],
            pref_audio=row["pref_audio"],
            pref_caption=bool(row["pref_caption"]),
        )

    @property
    def is_premium(self) -> bool:
        return bool(self.premium_until and self.premium_until > now_ts())

    @property
    def display_name(self) -> str:
        return self.first_name or (f"@{self.username}" if self.username else str(self.id))

    @property
    def mention(self) -> str:
        from bot.utils.text import esc

        return f'<a href="tg://user?id={self.id}">{esc(self.display_name)}</a>'


@dataclass(slots=True)
class CachedFile:
    key: str
    kind: str
    file_ids: list[str]
    title: str | None
    size: int | None
    created_at: int


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected; call `await db.connect()` first")
        return self._conn

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Cursor:
        cursor = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cursor

    async def executemany(self, sql: str, params: list[tuple[Any, ...]]) -> None:
        await self.conn.executemany(sql, params)
        await self.conn.commit()

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, params) as cursor:
            return list(await cursor.fetchall())

    async def scalar(self, sql: str, params: tuple[Any, ...] = (), default: Any = None) -> Any:
        row = await self.fetchone(sql, params)
        if row is None:
            return default
        value = row[0]
        return default if value is None else value


class Repository:
    """High level data access helpers."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ users
    async def upsert_user(
        self,
        user_id: int,
        username: str | None,
        first_name: str,
        *,
        language: str | None = None,
        referred_by: int | None = None,
    ) -> User:
        now = now_ts()
        existing = await self.db.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
        if existing is None:
            await self.db.execute(
                """INSERT INTO users
                   (id, username, first_name, language, created_at, last_seen, usage_date, referred_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, username, first_name[:128], language or "fa", now, now, today_key(), referred_by),
            )
        else:
            await self.db.execute(
                "UPDATE users SET username = ?, first_name = ?, last_seen = ? WHERE id = ?",
                (username, first_name[:128], now, user_id),
            )
        user = await self.get_user(user_id)
        assert user is not None
        return user

    async def get_user(self, user_id: int) -> User | None:
        row = await self.db.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
        return User.from_row(row) if row else None

    async def touch(self, user_id: int) -> None:
        await self.db.execute("UPDATE users SET last_seen = ? WHERE id = ?", (now_ts(), user_id))

    async def reset_daily(self, user_id: int) -> None:
        today = today_key()
        await self.db.execute(
            """UPDATE users
               SET downloads_today = 0, ai_today = 0, usage_date = ?
               WHERE id = ? AND (usage_date IS NULL OR usage_date != ?)""",
            (today, user_id, today),
        )

    async def set_language(self, user_id: int, language: str) -> None:
        await self.db.execute("UPDATE users SET language = ? WHERE id = ?", (language, user_id))

    async def set_pref(self, user_id: int, key: str, value: str | int) -> None:
        allowed = {"pref_quality", "pref_audio", "pref_caption"}
        if key not in allowed:
            raise ValueError(f"Unsupported preference: {key}")
        await self.db.execute(f"UPDATE users SET {key} = ? WHERE id = ?", (value, user_id))

    async def set_ban(self, user_id: int, banned: bool, reason: str | None = None) -> bool:
        cursor = await self.db.execute(
            "UPDATE users SET is_banned = ?, ban_reason = ? WHERE id = ?",
            (int(banned), reason, user_id),
        )
        return cursor.rowcount > 0

    async def grant_premium(self, user_id: int, days: int) -> int | None:
        user = await self.get_user(user_id)
        if user is None:
            return None
        base = max(now_ts(), user.premium_until or 0)
        until = base + days * 86400
        await self.db.execute("UPDATE users SET premium_until = ? WHERE id = ?", (until, user_id))
        return until

    async def revoke_premium(self, user_id: int) -> None:
        await self.db.execute("UPDATE users SET premium_until = NULL WHERE id = ?", (user_id,))

    async def register_referral(
        self, referrer_id: int, new_user_id: int, *, target: int, reward_days: int
    ) -> tuple[int, int | None]:
        """Count a successful invitation; grant premium on every target hit."""
        if referrer_id == new_user_id:
            return 0, None
        referrer = await self.get_user(referrer_id)
        if referrer is None or referrer.is_banned:
            return 0, None
        await self.db.execute("UPDATE users SET referral_count = referral_count + 1 WHERE id = ?", (referrer_id,))
        count = int(await self.db.scalar("SELECT referral_count FROM users WHERE id = ?", (referrer_id,), 0))
        reward: int | None = None
        if target > 0 and count % target == 0:
            until = await self.grant_premium(referrer_id, reward_days)
            reward = reward_days if until else None
        return count, reward

    async def set_referred_by(self, user_id: int, referrer_id: int) -> bool:
        cursor = await self.db.execute(
            "UPDATE users SET referred_by = ? WHERE id = ? AND referred_by IS NULL",
            (referrer_id, user_id),
        )
        return cursor.rowcount > 0

    # ------------------------------------------------------------------ quotas
    async def consume_download(self, user_id: int, limit: int, *, unlimited: bool = False) -> tuple[bool, int]:
        user = await self.get_user(user_id)
        if user is None:
            return False, 0
        await self.reset_daily(user_id)
        if not unlimited:
            used = int(await self.db.scalar("SELECT downloads_today FROM users WHERE id = ?", (user_id,), 0))
            if limit > 0 and used >= limit:
                return False, used
        await self.db.execute(
            """UPDATE users
               SET downloads_today = downloads_today + 1,
                   downloads_total = downloads_total + 1
               WHERE id = ?""",
            (user_id,),
        )
        used = int(await self.db.scalar("SELECT downloads_today FROM users WHERE id = ?", (user_id,), 0))
        return True, used

    async def refund_download(self, user_id: int) -> None:
        await self.db.execute(
            """UPDATE users
               SET downloads_today = MAX(0, downloads_today - 1),
                   downloads_total = MAX(0, downloads_total - 1)
               WHERE id = ?""",
            (user_id,),
        )

    async def consume_ai(self, user_id: int, limit: int, *, unlimited: bool = False) -> tuple[bool, int]:
        user = await self.get_user(user_id)
        if user is None:
            return False, 0
        await self.reset_daily(user_id)
        if not unlimited:
            used = int(await self.db.scalar("SELECT ai_today FROM users WHERE id = ?", (user_id,), 0))
            if limit > 0 and used >= limit:
                return False, used
        await self.db.execute(
            "UPDATE users SET ai_today = ai_today + 1, ai_total = ai_total + 1 WHERE id = ?",
            (user_id,),
        )
        used = int(await self.db.scalar("SELECT ai_today FROM users WHERE id = ?", (user_id,), 0))
        return True, used

    async def refund_ai(self, user_id: int) -> None:
        await self.db.execute(
            """UPDATE users
               SET ai_today = MAX(0, ai_today - 1),
                   ai_total = MAX(0, ai_total - 1)
               WHERE id = ?""",
            (user_id,),
        )

    # --------------------------------------------------------------- downloads
    async def log_download(self, user_id: int, url: str, platform: str, title: str | None, quality: str) -> int:
        cursor = await self.db.execute(
            """INSERT INTO downloads (user_id, url, platform, title, quality, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, url, platform, title, quality, now_ts()),
        )
        return int(cursor.lastrowid or 0)

    async def finish_download(
        self,
        download_id: int,
        status: str,
        *,
        size: int | None = None,
        duration: int | None = None,
        elapsed_ms: int | None = None,
        error: str | None = None,
    ) -> None:
        await self.db.execute(
            """UPDATE downloads
               SET status = ?, size = ?, duration = ?, elapsed_ms = ?, error = ?
               WHERE id = ?""",
            (status, size, duration, elapsed_ms, (error or "")[:500] or None, download_id),
        )

    async def downloads_count(self, user_id: int) -> int:
        return int(await self.db.scalar("SELECT COUNT(*) FROM downloads WHERE user_id = ?", (user_id,), 0))

    # -------------------------------------------------------------------- cache
    async def cache_get(self, key: str) -> CachedFile | None:
        row = await self.db.fetchone("SELECT * FROM file_cache WHERE key = ?", (key,))
        if row is None:
            return None
        try:
            file_ids = json.loads(row["file_ids"])
        except json.JSONDecodeError:
            return None
        if not isinstance(file_ids, list) or not file_ids:
            return None
        return CachedFile(
            key=row["key"],
            kind=row["kind"],
            file_ids=[str(item) for item in file_ids],
            title=row["title"],
            size=row["size"],
            created_at=row["created_at"],
        )

    async def cache_put(
        self,
        key: str,
        kind: str,
        file_ids: list[str],
        *,
        title: str | None = None,
        size: int | None = None,
    ) -> None:
        if not file_ids:
            return
        await self.db.execute(
            """INSERT INTO file_cache (key, kind, file_ids, title, size, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   kind = excluded.kind,
                   file_ids = excluded.file_ids,
                   title = excluded.title,
                   size = excluded.size,
                   created_at = excluded.created_at""",
            (key, kind, json.dumps(file_ids, ensure_ascii=False), title, size, now_ts()),
        )

    async def cache_delete(self, key: str) -> None:
        await self.db.execute("DELETE FROM file_cache WHERE key = ?", (key,))

    async def cache_cleanup(self, days: int = CACHE_TTL_DAYS) -> int:
        cutoff = now_ts() - days * 86400
        cursor = await self.db.execute("DELETE FROM file_cache WHERE created_at <= ?", (cutoff,))
        return cursor.rowcount

    async def cache_count(self) -> int:
        return int(await self.db.scalar("SELECT COUNT(*) FROM file_cache", (), 0))

    # ---------------------------------------------------------------- AI memory
    async def ai_add(self, user_id: int, role: str, content: str) -> None:
        await self.db.execute(
            "INSERT INTO ai_messages (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (user_id, role, content, now_ts()),
        )
        await self.db.execute(
            """DELETE FROM ai_messages WHERE user_id = ? AND id NOT IN
               (SELECT id FROM ai_messages WHERE user_id = ? ORDER BY id DESC LIMIT 40)""",
            (user_id, user_id),
        )

    async def ai_history(self, user_id: int, limit: int = 18) -> list[tuple[str, str]]:
        rows = await self.db.fetchall(
            "SELECT role, content FROM ai_messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        return [(row["role"], row["content"]) for row in reversed(rows)]

    async def ai_clear(self, user_id: int) -> None:
        await self.db.execute("DELETE FROM ai_messages WHERE user_id = ?", (user_id,))

    async def ai_count(self, user_id: int) -> int:
        return int(await self.db.scalar("SELECT COUNT(*) FROM ai_messages WHERE user_id = ?", (user_id,), 0))

    # ------------------------------------------------------------------ pending
    async def pending_create(
        self, kind: str, *, user_id: int | None = None, url: str | None = None, payload: Any = None
    ) -> str:
        token = secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:12]
        await self.db.execute(
            "INSERT INTO pending (token, user_id, kind, url, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                token,
                user_id,
                kind,
                url,
                json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                now_ts(),
            ),
        )
        return token

    async def pending_get(self, token: str) -> dict[str, Any] | None:
        row = await self.db.fetchone("SELECT * FROM pending WHERE token = ?", (token,))
        if row is None:
            return None
        if row["created_at"] < now_ts() - PENDING_TTL_SECONDS:
            await self.pending_delete(token)
            return None
        payload = None
        if row["payload"]:
            try:
                payload = json.loads(row["payload"])
            except json.JSONDecodeError:
                payload = None
        return {
            "token": row["token"],
            "user_id": row["user_id"],
            "kind": row["kind"],
            "url": row["url"],
            "payload": payload,
            "created_at": row["created_at"],
        }

    async def pending_delete(self, token: str) -> None:
        await self.db.execute("DELETE FROM pending WHERE token = ?", (token,))

    async def pending_cleanup(self) -> int:
        cursor = await self.db.execute("DELETE FROM pending WHERE created_at < ?", (now_ts() - PENDING_TTL_SECONDS,))
        return cursor.rowcount

    # --------------------------------------------------------------- deep links
    async def deep_link_create(self, user_id: int | None, url: str) -> str:
        token = secrets.token_urlsafe(10).replace("-", "").replace("_", "")[:14]
        await self.db.execute(
            "INSERT INTO deep_links (token, user_id, url, created_at) VALUES (?, ?, ?, ?)",
            (token, user_id, url, now_ts()),
        )
        return token

    async def deep_link_take(self, token: str) -> str | None:
        row = await self.db.fetchone("SELECT * FROM deep_links WHERE token = ?", (token,))
        if row is None:
            return None
        if row["created_at"] < now_ts() - DEEP_LINK_TTL_SECONDS:
            await self.db.execute("DELETE FROM deep_links WHERE token = ?", (token,))
            return None
        await self.db.execute("DELETE FROM deep_links WHERE token = ?", (token,))
        return row["url"]

    async def deep_links_cleanup(self) -> None:
        await self.db.execute("DELETE FROM deep_links WHERE created_at < ?", (now_ts() - DEEP_LINK_TTL_SECONDS,))

    # ----------------------------------------------------------------- settings
    async def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = await self.db.fetchone("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str | int | bool) -> None:
        await self.db.execute(
            """INSERT INTO settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, str(value)),
        )

    async def get_int_setting(self, key: str, default: int = 0) -> int:
        value = await self.get_setting(key)
        try:
            return int(value) if value is not None else default
        except ValueError:
            return default

    async def get_bool_setting(self, key: str, default: bool = False) -> bool:
        value = await self.get_setting(key)
        if value is None:
            return default
        return value.lower() in {"1", "true", "yes", "on"}

    async def bump_counter(self, key: str, amount: int = 1) -> int:
        await self.db.execute(
            """INSERT INTO counters (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = value + excluded.value""",
            (key, amount),
        )
        return int(await self.db.scalar("SELECT value FROM counters WHERE key = ?", (key,), 0))

    async def get_counter(self, key: str) -> int:
        return int(await self.db.scalar("SELECT value FROM counters WHERE key = ?", (key,), 0))

    # -------------------------------------------------------------------- stats
    async def stats(self) -> dict[str, Any]:
        now = now_ts()
        today = start_of_day_ts()
        week = now - 7 * 86400
        row = await self.db.fetchone(
            """SELECT
                 COUNT(*) AS users_total,
                 SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS users_today,
                 SUM(CASE WHEN last_seen >= ? THEN 1 ELSE 0 END) AS users_week,
                 SUM(CASE WHEN premium_until > ? THEN 1 ELSE 0 END) AS premium,
                 SUM(CASE WHEN is_banned = 1 THEN 1 ELSE 0 END) AS banned
               FROM users""",
            (today, week, now),
        )
        downloads = await self.db.fetchone(
            """SELECT
                 COUNT(*) AS total,
                 SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS today,
                 SUM(CASE WHEN status = 'done' AND created_at >= ? THEN 1 ELSE 0 END) AS done_today,
                 SUM(CASE WHEN status = 'failed' AND created_at >= ? THEN 1 ELSE 0 END) AS failed_today,
                 SUM(CASE WHEN status = 'done' THEN COALESCE(size, 0) ELSE 0 END) AS bytes
               FROM downloads""",
            (today, today, today),
        )
        ai = await self.db.fetchone(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS today
               FROM ai_messages WHERE role = 'user'""",
            (today,),
        )
        top = await self.db.fetchall(
            """SELECT platform, COUNT(*) AS count FROM downloads
               WHERE created_at >= ? AND platform != '' AND status = 'done'
               GROUP BY platform ORDER BY count DESC LIMIT 5""",
            (today,),
        )
        avg = await self.db.scalar(
            "SELECT AVG(elapsed_ms) FROM downloads WHERE status = 'done' AND created_at >= ?", (today,), 0
        )
        return {
            "users_total": row["users_total"] if row else 0,
            "users_today": row["users_today"] if row else 0,
            "users_week": row["users_week"] if row else 0,
            "premium": row["premium"] if row else 0,
            "banned": row["banned"] if row else 0,
            "downloads_total": downloads["total"] if downloads else 0,
            "downloads_today": downloads["today"] if downloads else 0,
            "downloads_done_today": downloads["done_today"] if downloads else 0,
            "downloads_failed_today": downloads["failed_today"] if downloads else 0,
            "downloads_bytes": downloads["bytes"] if downloads else 0,
            "ai_total": ai["total"] if ai else 0,
            "ai_today": ai["today"] if ai else 0,
            "top_platforms": [(r["platform"], r["count"]) for r in top],
            "avg_download_ms": int(avg or 0),
            "cache_count": await self.cache_count(),
            "cache_hits": await self.get_counter("cache_hits"),
            "cache_misses": await self.get_counter("cache_misses"),
        }

    async def recent_users(self, limit: int = 10) -> list[User]:
        rows = await self.db.fetchall("SELECT * FROM users ORDER BY created_at DESC LIMIT ?", (limit,))
        return [User.from_row(row) for row in rows]

    async def search_users(self, query: str, limit: int = 10) -> list[User]:
        query = query.strip().lstrip("@")
        rows = await self.db.fetchall(
            """SELECT * FROM users
               WHERE CAST(id AS TEXT) = ? OR username LIKE ? COLLATE NOCASE
               ORDER BY last_seen DESC LIMIT ?""",
            (query, f"%{query}%", limit),
        )
        return [User.from_row(row) for row in rows]

    async def all_user_ids(self, *, include_banned: bool = False) -> list[int]:
        sql = "SELECT id FROM users"
        if not include_banned:
            sql += " WHERE is_banned = 0"
        rows = await self.db.fetchall(sql)
        return [int(row["id"]) for row in rows]

    async def cleanup(self) -> None:
        await self.cache_cleanup()
        await self.pending_cleanup()
        await self.deep_links_cleanup()
