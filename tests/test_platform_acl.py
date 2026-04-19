"""Tests for US-003: Platform ACL migration and allowed_platforms query helper."""
from __future__ import annotations

import asyncio
import os
import re

import aiosqlite
import pytest

import hermit_agent.gateway.db as db_mod
from hermit_agent.gateway.db import allowed_platforms


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MIGRATIONS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "hermit_agent", "gateway", "migrations"
)


def _sql_path(name: str) -> str:
    return os.path.join(_MIGRATIONS_DIR, name)


async def _apply_sql(db: aiosqlite.Connection, path: str) -> None:
    with open(path) as f:
        sql = f.read()
    await db.executescript(sql)
    await db.commit()


async def _seed_db(db_path: str) -> None:
    """Apply migration 001, then 002."""
    async with aiosqlite.connect(db_path) as db:
        await _apply_sql(db, _sql_path("001_initial.sql"))


async def _apply_002(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await _apply_sql(db, _sql_path("002_platform_acl.sql"))


async def _insert_api_key(db_path: str, api_key: str, user: str = "testuser") -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT OR IGNORE INTO api_keys (api_key, user) VALUES (?, ?)",
            (api_key, user),
        )
        await db.commit()


async def _insert_platform_row(db_path: str, api_key: str, platform_slug: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT OR IGNORE INTO api_key_platform (api_key, platform_slug) VALUES (?, ?)",
            (api_key, platform_slug),
        )
        await db.commit()


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Temporary SQLite DB with 001 applied; patches db.DB_PATH."""
    db_file = str(tmp_path / "test_gateway.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    asyncio.run(_seed_db(db_file))
    return db_file


# ---------------------------------------------------------------------------
# Schema / FK correctness (text-based check — no DB needed)
# ---------------------------------------------------------------------------

def test_migration_fk_column_matches_api_keys_schema():
    """002 must reference api_keys(api_key), not api_keys(token)."""
    with open(_sql_path("002_platform_acl.sql")) as f:
        sql = f.read()
    # Find FK line referencing api_keys
    fk_match = re.search(
        r"FOREIGN KEY\s*\(api_key\)\s+REFERENCES\s+api_keys\s*\((\w+)\)",
        sql,
        re.IGNORECASE,
    )
    assert fk_match is not None, "FK on api_key column not found in 002_platform_acl.sql"
    referenced_col = fk_match.group(1)
    assert referenced_col == "api_key", (
        f"FK references api_keys({referenced_col}), expected api_keys(api_key)"
    )


# ---------------------------------------------------------------------------
# Backfill: existing keys get all platforms after migration 002
# ---------------------------------------------------------------------------

def test_migration_backfills_existing_keys_with_all_platforms(tmp_db):
    """A key seeded BEFORE migration 002 must receive all 4 platform rows."""
    key = "pre-existing-key"
    asyncio.run(_insert_api_key(tmp_db, key))
    asyncio.run(_apply_002(tmp_db))

    result = asyncio.run(allowed_platforms(key))
    assert result == {"local", "z.ai", "anthropic", "codex"}


# ---------------------------------------------------------------------------
# allowed_platforms behaviour
# ---------------------------------------------------------------------------

def test_full_access_key(tmp_db):
    """Key with rows for all platforms returns the full set."""
    key = "full-access-key"
    asyncio.run(_insert_api_key(tmp_db, key))
    asyncio.run(_apply_002(tmp_db))

    result = asyncio.run(allowed_platforms(key))
    assert result == {"local", "z.ai", "anthropic", "codex"}


def test_local_only_key(tmp_db):
    """Key with only a 'local' row returns {'local'}."""
    asyncio.run(_apply_002(tmp_db))

    key = "local-only-key"
    asyncio.run(_insert_api_key(tmp_db, key))
    asyncio.run(_insert_platform_row(tmp_db, key, "local"))

    result = asyncio.run(allowed_platforms(key))
    assert result == {"local"}


def test_unknown_key_returns_empty(tmp_db):
    """A key not in api_keys returns an empty set."""
    asyncio.run(_apply_002(tmp_db))

    result = asyncio.run(allowed_platforms("nonexistent-key"))
    assert result == set()


def test_default_deny_key_exists_but_no_platform_rows(tmp_db):
    """Key in api_keys but with no api_key_platform rows returns empty set."""
    asyncio.run(_apply_002(tmp_db))

    key = "no-platforms-key"
    asyncio.run(_insert_api_key(tmp_db, key))
    # Do NOT insert any api_key_platform rows for this key.

    result = asyncio.run(allowed_platforms(key))
    assert result == set()


# ---------------------------------------------------------------------------
# Platforms seed
# ---------------------------------------------------------------------------

def test_platforms_seeded(tmp_db):
    """After migration 002, the platforms table must have exactly 4 rows."""
    asyncio.run(_apply_002(tmp_db))

    async def _query():
        async with aiosqlite.connect(tmp_db) as db:
            rows = await db.execute_fetchall("SELECT slug FROM platforms ORDER BY slug")
            return {r[0] for r in rows}

    slugs = asyncio.run(_query())
    assert slugs == {"local", "z.ai", "anthropic", "codex"}


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_migration_idempotency(tmp_db):
    """Applying migration 002 twice raises no error and creates no duplicate rows."""
    key = "idem-key"
    asyncio.run(_insert_api_key(tmp_db, key))

    # Apply twice
    asyncio.run(_apply_002(tmp_db))
    asyncio.run(_apply_002(tmp_db))  # must not raise

    async def _count_platform_rows():
        async with aiosqlite.connect(tmp_db) as db:
            rows = await db.execute_fetchall(
                "SELECT COUNT(*) FROM api_key_platform WHERE api_key = ?", (key,)
            )
            return rows[0][0]

    count = asyncio.run(_count_platform_rows())
    assert count == 4, f"Expected 4 platform rows for key after idempotent apply, got {count}"
