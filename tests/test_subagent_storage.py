"""G2 — Verify saving of separate subagent JSONL + meta.json."""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermit_agent.session_logger import SessionLogger


def _make_session_dir(tmp: str) -> str:
    session_dir = os.path.join(tmp, ".hermit", "session")
    os.makedirs(session_dir, exist_ok=True)
    return session_dir


def test_subagent_logger_creates_jsonl_and_meta():
    with tempfile.TemporaryDirectory() as tmp:
        parent = SessionLogger(session_dir=_make_session_dir(tmp))
        sub = parent.create_subagent_logger(
            agent_id="abc123",
            agent_type="explore",
            description="search for foo",
        )

        # A jsonl file + meta.json file must be created.
        assert os.path.exists(sub.jsonl_path)
        assert sub.jsonl_path.endswith("agent-abc123.jsonl")
        meta_path = sub.meta_path
        assert os.path.exists(meta_path)
        assert meta_path.endswith("agent-abc123.meta.json")

        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        assert meta["agentType"] == "explore"
        assert meta["description"] == "search for foo"
        assert meta["agent_id"] == "abc123"
        assert meta["parent_session_id"] == parent.session_id
        assert "started_at" in meta


def test_subagent_dispatch_attachment_in_parent():
    """A subagent_dispatch attachment remains in the parent session.jsonl."""
    with tempfile.TemporaryDirectory() as tmp:
        parent = SessionLogger(session_dir=_make_session_dir(tmp))
        parent.create_subagent_logger("xyz", "executor", "implement feature X")

        records = []
        with open(parent.jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        disp = [
            r for r in records
            if r.get("type") == "attachment" and r.get("kind") == "subagent_dispatch"
        ]
        assert len(disp) == 1
        assert disp[0]["agent_id"] == "xyz"
        assert "implement feature X" in disp[0]["content"]


def test_subagent_finish_writes_meta():
    with tempfile.TemporaryDirectory() as tmp:
        parent = SessionLogger(session_dir=_make_session_dir(tmp))
        sub = parent.create_subagent_logger("aa", "explore", "desc")
        sub.finish(result_summary="found 3 files")

        with open(sub.meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        assert "ended_at" in meta
        assert meta.get("result_summary") == "found 3 files"
