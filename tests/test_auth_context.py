"""Tests for US-003.5: AuthContext carries raw api_key through Depends()."""
from __future__ import annotations

import asyncio
import os

import aiosqlite
import pytest

import hermit_agent.gateway.db as db_mod
from hermit_agent.gateway.auth import AuthContext, get_current_user


_MIGRATIONS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "hermit_agent", "gateway", "migrations"
)


async def _seed_db(db_path: str) -> None:
    sql_path = os.path.join(_MIGRATIONS_DIR, "001_initial.sql")
    with open(sql_path) as f:
        sql = f.read()
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(sql)
        await db.commit()


async def _insert_api_key(db_path: str, api_key: str, user: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT OR IGNORE INTO api_keys (api_key, user) VALUES (?, ?)",
            (api_key, user),
        )
        await db.commit()


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Temporary SQLite DB with 001 applied; patches db.DB_PATH."""
    db_file = str(tmp_path / "test_gateway.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    asyncio.run(_seed_db(db_file))
    return db_file


class _FakeCreds:
    """Minimal stand-in for HTTPAuthorizationCredentials."""
    def __init__(self, token: str):
        self.credentials = token


def test_get_current_user_returns_auth_context_with_api_key(tmp_db):
    """get_current_user must return AuthContext(user=..., api_key=<token>)."""
    token = "test-token-abc123"
    asyncio.run(_insert_api_key(tmp_db, token, "alice"))

    result = asyncio.run(get_current_user(creds=_FakeCreds(token)))

    assert isinstance(result, AuthContext)
    assert result.user == "alice"
    assert result.api_key == token


def test_auth_context_missing_token_raises_unauthorized(tmp_db):
    """No credentials → 401 UNAUTHORIZED."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_current_user(creds=None))

    assert exc_info.value.status_code == 401


def test_auth_context_invalid_token_raises_unauthorized(tmp_db):
    """Unknown token → 401 UNAUTHORIZED."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_current_user(creds=_FakeCreds("not-in-db")))

    assert exc_info.value.status_code == 401
