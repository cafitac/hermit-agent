from __future__ import annotations
import logging
import os

import aiosqlite

logger = logging.getLogger("hermit_agent.gateway.db")

DB_PATH = os.environ.get("HERMIT_GATEWAY_DB", os.path.expanduser("~/.hermit/gateway.db"))

_MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")


async def init_db() -> None:
    """DB initialization: WAL mode, migrations, env var key migration."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")

        # If legacy schema_version table exists, migrate to applied_migrations
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if await cur.fetchone():
            await db.execute(
                "CREATE TABLE IF NOT EXISTS applied_migrations "
                "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
            )
            ver_cur = await db.execute("SELECT version FROM schema_version")
            ver_row = await ver_cur.fetchone()
            if ver_row and ver_row[0] >= 1:
                await db.execute(
                    "INSERT OR IGNORE INTO applied_migrations (name) VALUES ('001_initial.sql')"
                )
            await db.execute("DROP TABLE schema_version")
            await db.commit()
            logger.info("Migrated schema_version → applied_migrations")

        # Ensure applied_migrations table exists
        await db.execute(
            "CREATE TABLE IF NOT EXISTS applied_migrations "
            "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        await db.commit()

        # Run migrations
        await _run_pending_migrations(db)

        # On first run, migrate keys from env vars to DB
        await _migrate_env_keys(db)


async def _run_pending_migrations(db: aiosqlite.Connection) -> None:
    """Execute pending SQL files from migrations/ directory in order."""
    if not os.path.isdir(_MIGRATIONS_DIR):
        return

    files = sorted(f for f in os.listdir(_MIGRATIONS_DIR) if f.endswith(".sql"))
    for fname in files:
        cur = await db.execute(
            "SELECT 1 FROM applied_migrations WHERE name = ?", (fname,)
        )
        if await cur.fetchone():
            continue

        sql_path = os.path.join(_MIGRATIONS_DIR, fname)
        with open(sql_path) as f:
            sql = f.read()

        await db.executescript(sql)
        await db.execute(
            "INSERT INTO applied_migrations (name) VALUES (?)", (fname,)
        )
        await db.commit()
        logger.info("Applied migration: %s", fname)


async def _migrate_env_keys(db: aiosqlite.Connection) -> None:
    """Migrate GATEWAY_API_KEYS / GATEWAY_USER_MAP env vars to DB."""
    keys_raw = os.environ.get("GATEWAY_API_KEYS", "")
    user_map_raw = os.environ.get("GATEWAY_USER_MAP", "")
    if not keys_raw:
        return
    keys = {k.strip() for k in keys_raw.split(",") if k.strip()}
    user_map: dict[str, str] = {}
    for pair in user_map_raw.split(","):
        if ":" in pair:
            k, u = pair.strip().split(":", 1)
            user_map[k.strip()] = u.strip()
    for key in keys:
        user = user_map.get(key, "anonymous")
        await db.execute(
            "INSERT OR IGNORE INTO api_keys (api_key, user) VALUES (?, ?)",
            (key, user),
        )
    await db.commit()


async def lookup_api_key(token: str) -> str | None:
    """Return username for a token. Looks up DB first, falls back to env vars."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT user FROM api_keys WHERE api_key = ? AND active = 1",
            (token,),
        )
        row = await cur.fetchone()
        if row:
            return row["user"]
    # env var fallback
    keys_raw = os.environ.get("GATEWAY_API_KEYS", "")
    user_map_raw = os.environ.get("GATEWAY_USER_MAP", "")
    keys = {k.strip() for k in keys_raw.split(",") if k.strip()}
    if token in keys:
        user_map: dict[str, str] = {}
        for pair in user_map_raw.split(","):
            if ":" in pair:
                k, u = pair.strip().split(":", 1)
                user_map[k.strip()] = u.strip()
        return user_map.get(token, "anonymous")
    return None


async def list_api_keys() -> list[dict]:
    """Return all API keys."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, api_key, user, active, created_at FROM api_keys ORDER BY created_at DESC"
        )
        return [dict(r) for r in await cursor.fetchall()]


async def create_api_key(api_key: str, user: str, *, grant_all_platforms: bool = False) -> None:
    """Generate an API key. Pass grant_all_platforms=True to authorize all known platforms."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO api_keys (api_key, user) VALUES (?, ?)",
            (api_key, user),
        )
        if grant_all_platforms:
            rows = await db.execute_fetchall("SELECT slug FROM platforms")
            for (slug,) in rows:
                await db.execute(
                    "INSERT OR IGNORE INTO api_key_platform (api_key, platform_slug) VALUES (?, ?)",
                    (api_key, slug),
                )
        await db.commit()


async def delete_api_key(api_key: str) -> bool:
    """Delete an API key. Returns number of deleted rows."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM api_keys WHERE api_key = ?", (api_key,))
        await db.commit()
        return cur.rowcount > 0


async def insert_usage(
    user: str,
    task_id: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    duration_ms: int,
    status: str,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO token_usage
               (user, task_id, model, prompt_tokens, completion_tokens, duration_ms, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user, task_id, model, prompt_tokens, completion_tokens, duration_ms, status),
        )
        await db.commit()


async def query_usage(user: str | None, days: int = 7) -> list[dict]:
    if user:
        sql = """SELECT user, date(created_at) AS day, model,
                        SUM(prompt_tokens) AS prompt_tokens,
                        SUM(completion_tokens) AS completion_tokens,
                        COUNT(*) AS requests, AVG(duration_ms) AS avg_duration_ms
                 FROM token_usage
                 WHERE created_at >= datetime('now', ?) AND user = ?
                 GROUP BY user, day, model ORDER BY day DESC"""
        params: list = [f"-{days} days", user]
    else:
        sql = """SELECT user, date(created_at) AS day, model,
                        SUM(prompt_tokens) AS prompt_tokens,
                        SUM(completion_tokens) AS completion_tokens,
                        COUNT(*) AS requests, AVG(duration_ms) AS avg_duration_ms
                 FROM token_usage
                 WHERE created_at >= datetime('now', ?)
                 GROUP BY user, day, model ORDER BY day DESC, user"""
        params = [f"-{days} days"]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(sql, params)
        return [dict(r) for r in await cursor.fetchall()]


async def allowed_platforms(api_key: str) -> set[str]:
    """Return the set of platform slugs this key is allowed to access.

    Returns an empty set when the key has no rows (default-deny).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall(
            "SELECT platform_slug FROM api_key_platform WHERE api_key = ?",
            (api_key,),
        )
        return {r[0] for r in rows}


async def query_recent_tasks(limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT task_id, user, model, status, prompt_tokens, completion_tokens, created_at
               FROM token_usage ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in await cursor.fetchall()]
