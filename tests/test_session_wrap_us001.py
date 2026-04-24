"""US-001: compact-hook handoff artifacts — Red-Green tests.

Coverage:
- build_handoff_rich: 5-section markdown, no LLM
- save_handoff prefix kwarg + chmod 0o600
- _gc_handoffs: keeps at most max_keep files
- save_pre_compact_snapshot: pre-compact- prefix, chmod 0o600, raw message dump
"""

from __future__ import annotations

import os
import sys
import stat
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermit_agent.session_wrap import (
    build_handoff_rich,
    save_handoff,
    save_pre_compact_snapshot,
    _gc_handoffs,
)


# ─── build_handoff_rich ──────────────────────────────────────────────


def _sample_messages() -> list[dict]:
    return [
        {"role": "user", "content": "Implement the login feature."},
        {"role": "assistant", "content": "Sure, I will start by reading the auth module."},
        {"role": "user", "content": "Also add tests please."},
        {"role": "assistant", "content": "Got it. Reading /app/auth.py now."},
        {"role": "user", "content": "There is a Traceback: error in line 42."},
    ]


def test_build_handoff_rich_returns_string():
    md = build_handoff_rich(_sample_messages(), session_id="abc12345")
    assert isinstance(md, str)
    assert len(md) > 50


def test_build_handoff_rich_has_required_sections():
    md = build_handoff_rich(_sample_messages(), session_id="abc12345")
    assert "## Primary Request" in md
    assert "## All User Messages" in md
    assert "## Files Touched" in md
    assert "## Current Work" in md
    assert "## Errors and Fixes" in md


def test_build_handoff_rich_includes_primary_request():
    md = build_handoff_rich(_sample_messages(), session_id="abc12345")
    assert "Implement the login feature." in md


def test_build_handoff_rich_captures_user_messages():
    md = build_handoff_rich(_sample_messages(), session_id="abc12345")
    assert "Also add tests please." in md


def test_build_handoff_rich_captures_errors():
    md = build_handoff_rich(_sample_messages(), session_id="abc12345")
    # "Traceback" keyword triggers error capture
    assert "Traceback" in md or "error in line 42" in md


def test_build_handoff_rich_no_llm_call():
    """build_handoff_rich must be purely rule-based — no LLM attribute."""
    import inspect
    src = inspect.getsource(build_handoff_rich)
    # Must not call any llm.chat or requests.post
    assert "llm.chat" not in src
    assert "requests.post" not in src


def test_build_handoff_rich_session_id_in_header():
    md = build_handoff_rich(_sample_messages(), session_id="deadbeef1234")
    assert "deadbeef" in md  # first 8 chars


def test_build_handoff_rich_none_session_id():
    md = build_handoff_rich(_sample_messages(), session_id=None)
    assert "unknown" in md


def test_build_handoff_rich_empty_messages():
    md = build_handoff_rich([], session_id="s1")
    assert "## Primary Request" in md
    assert "none recorded" in md.lower() or "_(none" in md


# ─── save_handoff prefix kwarg ───────────────────────────────────────


def test_save_handoff_prefix_kwarg():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_handoff("content", session_id="abc12345", cwd=tmp, prefix="auto-compact-")
        assert path.name.startswith("auto-compact-")
        assert path.exists()


def test_save_handoff_prefix_with_sid():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_handoff("c", session_id="abc12345", cwd=tmp, prefix="pre-compact-")
        # must contain the first 8 chars of sid
        assert "abc12345" in path.name


def test_save_handoff_prefix_none_uses_legacy():
    """No prefix → legacy YYYYMMDD-HHMMSS_sid format (unchanged)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = save_handoff("c", session_id="sid", cwd=tmp)
        assert "sid" in path.name
        assert not path.name.startswith("auto-compact-")


def test_save_handoff_chmod_0o600():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_handoff("secret", session_id="s1", cwd=tmp)
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600


def test_save_handoff_prefix_chmod_0o600():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_handoff("secret", session_id="s1", cwd=tmp, prefix="auto-compact-")
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600


# ─── _gc_handoffs ────────────────────────────────────────────────────


def test_gc_handoffs_removes_oldest_when_exceeds_max():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        # Create 25 files with distinct mtimes
        for i in range(25):
            p = d / f"handoff_{i:03d}.md"
            p.write_text(f"content {i}")
            # Stagger mtime so sort is deterministic
            os.utime(p, (i * 10, i * 10))

        _gc_handoffs(d, max_keep=20)

        remaining = sorted(d.glob("*.md"))
        assert len(remaining) == 20
        # The 5 oldest (indices 0-4, lowest mtime) must be gone
        names = {p.name for p in remaining}
        for i in range(5):
            assert f"handoff_{i:03d}.md" not in names


def test_gc_handoffs_no_op_when_under_limit():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for i in range(10):
            (d / f"f_{i}.md").write_text("x")

        _gc_handoffs(d, max_keep=20)
        assert len(list(d.glob("*.md"))) == 10


def test_gc_handoffs_does_not_raise_on_empty_dir():
    with tempfile.TemporaryDirectory() as tmp:
        _gc_handoffs(Path(tmp), max_keep=20)  # must not raise


# ─── save_pre_compact_snapshot ───────────────────────────────────────


def test_save_pre_compact_snapshot_creates_file():
    msgs = [{"role": "user", "content": "hello"}]
    with tempfile.TemporaryDirectory() as tmp:
        path = save_pre_compact_snapshot(msgs, session_id="abc12345", cwd=tmp)
        assert path.exists()


def test_save_pre_compact_snapshot_prefix():
    msgs = [{"role": "user", "content": "hello"}]
    with tempfile.TemporaryDirectory() as tmp:
        path = save_pre_compact_snapshot(msgs, session_id="abc12345", cwd=tmp)
        assert path.name.startswith("pre-compact-")


def test_save_pre_compact_snapshot_chmod_0o600():
    msgs = [{"role": "user", "content": "hello"}]
    with tempfile.TemporaryDirectory() as tmp:
        path = save_pre_compact_snapshot(msgs, session_id="abc12345", cwd=tmp)
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600


def test_save_pre_compact_snapshot_contains_message_content():
    msgs = [
        {"role": "user", "content": "unique-marker-xyz"},
        {"role": "assistant", "content": "response here"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = save_pre_compact_snapshot(msgs, session_id="s1", cwd=tmp)
        text = path.read_text()
        assert "unique-marker-xyz" in text


def test_save_pre_compact_snapshot_total_messages_header():
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(7)]
    with tempfile.TemporaryDirectory() as tmp:
        path = save_pre_compact_snapshot(msgs, session_id="s1", cwd=tmp)
        text = path.read_text()
        assert "Total messages: 7" in text
