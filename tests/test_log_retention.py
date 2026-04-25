from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import hermit_agent.log_retention as _lr
from hermit_agent.log_retention import append_jsonl_record, append_text_log, prune_oldest_files, rotate_text_log
from hermit_agent.session.store import SessionStore
from hermit_agent.session.logger import SessionLogger


def test_rotate_text_log_creates_backup_when_over_limit(tmp_path):
    log_path = tmp_path / "gateway.log"
    log_path.write_text("x" * 32, encoding="utf-8")

    rotate_text_log(str(log_path), max_bytes=16, backups=2)

    assert not log_path.exists()
    assert (tmp_path / "gateway.log.1").exists()


def test_append_text_log_rotates_and_appends(tmp_path):
    log_path = tmp_path / "mcp_server.log"
    log_path.write_text("x" * 32, encoding="utf-8")

    append_text_log(str(log_path), "fresh\n", max_bytes=16, backups=2)

    assert (tmp_path / "mcp_server.log.1").exists()
    assert log_path.read_text(encoding="utf-8") == "fresh\n"


def test_append_jsonl_record_rotates_and_appends(tmp_path):
    log_path = tmp_path / "events.jsonl"
    log_path.write_text('{"old":1}\n' * 8, encoding="utf-8")

    append_jsonl_record(str(log_path), '{"new":1}\n', max_bytes=16, backups=2)

    assert (tmp_path / "events.jsonl.1").exists()
    assert log_path.read_text(encoding="utf-8") == '{"new":1}\n'


def test_prune_oldest_files_keeps_newest_n(tmp_path):
    for idx in range(4):
        path = tmp_path / f"{idx}.jsonl"
        path.write_text(str(idx), encoding="utf-8")

    prune_oldest_files(tmp_path, pattern="*.jsonl", max_keep=2)

    remaining = sorted(p.name for p in tmp_path.glob("*.jsonl"))
    assert remaining == ["2.jsonl", "3.jsonl"]


def test_session_store_prunes_old_inactive_sessions(tmp_path):
    store = SessionStore(root=str(tmp_path / "logs"))
    session_dirs: list[str] = []
    for idx in range(3):
        session_dir = store.create_session(mode="gateway", session_id=f"s{idx}", cwd="/x")
        store.update_meta(session_dir, status="completed", turn_count=idx + 1)
        session_dirs.append(session_dir)

    for idx, session_dir in enumerate(session_dirs):
        meta_path = Path(session_dir) / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["updated_at"] = f"2026-04-2{idx}T00:00:00Z"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    store._prune_mode_bucket(mode="gateway", cwd="/x", keep=1)

    bucket = Path(tmp_path / "logs" / "gateway" / "-x")
    remaining = sorted(p.name for p in bucket.iterdir() if p.is_dir())
    assert remaining == ["s2"]


def test_makedirs_called_once_per_directory(tmp_path):
    """os.makedirs should be skipped on repeat calls to the same directory."""
    log_path = str(tmp_path / "sub" / "app.log")
    _lr._created_dirs.clear()

    with patch("hermit_agent.log_retention.os.makedirs", wraps=_lr.os.makedirs) as mock_mk:
        append_text_log(log_path, "line1\n")
        append_text_log(log_path, "line2\n")
        append_text_log(log_path, "line3\n")

    assert mock_mk.call_count == 1


def test_session_logger_rotates_event_log_when_over_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("hermit_agent.log_retention.DEFAULT_JSONL_LOG_MAX_BYTES", 16)
    monkeypatch.setattr("hermit_agent.log_retention.DEFAULT_JSONL_LOG_BACKUPS", 2)

    session_dir = tmp_path / "session"
    session_dir.mkdir()
    events_path = session_dir / "events.jsonl"
    events_path.write_text('{"old":1}\n' * 8, encoding="utf-8")

    logger = SessionLogger(session_dir=str(session_dir))
    logger.log_user("fresh")

    assert (session_dir / "events.jsonl.1").exists()
    contents = events_path.read_text(encoding="utf-8")
    assert "fresh" in contents
