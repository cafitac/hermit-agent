"""US-003: handoff seed injection helpers — Red-Green tests.

Coverage:
- _pick_latest_handoff: priority (auto-compact > pre-compact > misc .md)
- _pick_latest_handoff: skips consumed filenames
- _pick_latest_handoff: returns None when dir missing or all consumed
- _load_consumed: JSONL read, missing file -> empty set, malformed lines skipped
- _mark_consumed: JSONL append, creates file on first call
- loop.py seed injection: <session-handoff> prepended on coding path (NEED_TOOLS)
- loop.py seed injection: NOT prepended on casual chat path (classify returned text)
- loop.py seed injection: 2000-char hard cap with truncation marker
- loop.py seed injection: skipped when max_context_tokens < 16000
- loop.py seed injection: skipped when HERMIT_SEED_HANDOFF=0
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hermit_agent.session_wrap import (
    _load_consumed,
    _mark_consumed,
    _pick_latest_handoff,
)


# ─── _pick_latest_handoff ────────────────────────────────────────────


def test_pick_prefers_auto_compact_over_pre_compact(tmp_path):
    """auto-compact-*.md must win over pre-compact-*.md."""
    (tmp_path / "pre-compact-20260101-120000.md").write_text("pre")
    (tmp_path / "auto-compact-20260101-120001.md").write_text("auto")

    result = _pick_latest_handoff(tmp_path, consumed=set())
    assert result is not None
    assert result.name.startswith("auto-compact-")


def test_pick_prefers_pre_compact_over_misc(tmp_path):
    """pre-compact-*.md must win over misc *.md."""
    (tmp_path / "20260101-120000.md").write_text("misc")
    (tmp_path / "pre-compact-20260101-120001.md").write_text("pre")

    result = _pick_latest_handoff(tmp_path, consumed=set())
    assert result is not None
    assert result.name.startswith("pre-compact-")


def test_pick_skips_consumed(tmp_path):
    """Already-consumed files must be skipped."""
    name = "auto-compact-20260101-120000.md"
    (tmp_path / name).write_text("auto")

    result = _pick_latest_handoff(tmp_path, consumed={name})
    assert result is None


def test_pick_falls_through_to_next_tier(tmp_path):
    """When top-tier file is consumed, falls through to next tier."""
    auto_name = "auto-compact-20260101-120000.md"
    (tmp_path / auto_name).write_text("auto")
    (tmp_path / "pre-compact-20260101-120001.md").write_text("pre")

    result = _pick_latest_handoff(tmp_path, consumed={auto_name})
    assert result is not None
    assert result.name.startswith("pre-compact-")


def test_pick_returns_none_for_missing_dir(tmp_path):
    """Missing directory returns None."""
    missing = tmp_path / "nonexistent"
    result = _pick_latest_handoff(missing, consumed=set())
    assert result is None


def test_pick_returns_none_when_all_consumed(tmp_path):
    """All files consumed -> None."""
    name = "20260101-120000.md"
    (tmp_path / name).write_text("misc")

    result = _pick_latest_handoff(tmp_path, consumed={name})
    assert result is None


def test_pick_latest_within_tier_by_filename(tmp_path):
    """Within the same tier, the lexicographically latest filename is chosen."""
    (tmp_path / "auto-compact-20260101-110000.md").write_text("older")
    (tmp_path / "auto-compact-20260101-120000.md").write_text("newer")

    result = _pick_latest_handoff(tmp_path, consumed=set())
    assert result is not None
    assert "120000" in result.name  # newer one


# ─── _load_consumed ──────────────────────────────────────────────────


def test_load_consumed_missing_file(tmp_path):
    """Missing .consumed file returns empty set."""
    result = _load_consumed(tmp_path)
    assert result == set()


def test_load_consumed_reads_filenames(tmp_path):
    """Valid JSONL lines are parsed into filename set."""
    consumed_file = tmp_path / ".consumed"
    consumed_file.write_text(
        json.dumps({"file": "a.md", "consumed_at": "2026-01-01T12:00:00"}) + "\n"
        + json.dumps({"file": "b.md", "consumed_at": "2026-01-01T13:00:00"}) + "\n"
    )
    result = _load_consumed(tmp_path)
    assert result == {"a.md", "b.md"}


def test_load_consumed_skips_malformed_lines(tmp_path):
    """Malformed JSON lines are silently skipped."""
    consumed_file = tmp_path / ".consumed"
    consumed_file.write_text(
        "not json\n"
        + json.dumps({"file": "good.md", "consumed_at": "2026-01-01T12:00:00"}) + "\n"
        + "{broken\n"
    )
    result = _load_consumed(tmp_path)
    assert result == {"good.md"}


def test_load_consumed_skips_blank_lines(tmp_path):
    """Blank lines don't cause errors."""
    consumed_file = tmp_path / ".consumed"
    consumed_file.write_text(
        "\n"
        + json.dumps({"file": "ok.md", "consumed_at": "2026-01-01T12:00:00"}) + "\n"
        + "\n"
    )
    result = _load_consumed(tmp_path)
    assert result == {"ok.md"}


# ─── _mark_consumed ──────────────────────────────────────────────────


def test_mark_consumed_creates_file(tmp_path):
    """_mark_consumed creates .consumed on first call."""
    _mark_consumed(tmp_path, "new.md")
    consumed_file = tmp_path / ".consumed"
    assert consumed_file.is_file()
    lines = [line for line in consumed_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["file"] == "new.md"
    assert "consumed_at" in rec


def test_mark_consumed_appends(tmp_path):
    """Multiple calls append lines, not overwrite."""
    _mark_consumed(tmp_path, "first.md")
    _mark_consumed(tmp_path, "second.md")
    consumed_file = tmp_path / ".consumed"
    lines = [line for line in consumed_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 2
    names = {json.loads(line)["file"] for line in lines}
    assert names == {"first.md", "second.md"}


def test_mark_consumed_roundtrip(tmp_path):
    """_mark_consumed + _load_consumed roundtrip works."""
    _mark_consumed(tmp_path, "handoff.md")
    result = _load_consumed(tmp_path)
    assert "handoff.md" in result


# ─── loop.py seed injection ──────────────────────────────────────────


def _make_agent(tmp_path, max_context_tokens=32000, seed_handoff=True):
    """Build a minimal AgentLoop with stubbed dependencies."""
    from hermit_agent.loop import AgentLoop
    from hermit_agent.llm_client import LLMResponse

    llm = MagicMock()
    llm.model = "test-model"
    # classify call: return None (NEED_TOOLS path)
    llm.chat.return_value = LLMResponse(content="NEED_TOOLS", tool_calls=[])

    agent = AgentLoop.__new__(AgentLoop)
    agent.llm = llm
    agent.messages = []
    agent._context_injected = False
    agent._dynamic_context = ""
    agent.cwd = str(tmp_path)
    agent.session_id = "test-session"
    agent.seed_handoff = seed_handoff
    agent.abort_event = MagicMock()
    agent.abort_event.is_set.return_value = False

    # Stub context_manager
    cm = MagicMock()
    cm.max_context_tokens = max_context_tokens
    agent.context_manager = cm

    # Other attrs accessed during run()
    agent._last_text_sig = ""
    agent._text_repeat_count = 0
    agent._skill_active = False
    agent._auto_continue_count = 0
    agent.token_totals = {"prompt_tokens": 0, "completion_tokens": 0}
    agent._pinned_reminders = []

    return agent


def _write_handoff(handoffs_dir: Path, name: str, content: str = "handoff content") -> Path:
    handoffs_dir.mkdir(parents=True, exist_ok=True)
    p = handoffs_dir / name
    p.write_text(content)
    return p


def test_seed_injected_on_coding_path(tmp_path, monkeypatch):
    """On NEED_TOOLS path, <session-handoff> is prepended to user_message."""
    handoffs_dir = tmp_path / ".hermit" / "handoffs"
    _write_handoff(handoffs_dir, "auto-compact-20260101-120000.md", "# Handoff content\nSome detail.")

    agent = _make_agent(tmp_path, max_context_tokens=32000)

    # Stub _run_loop to capture the messages list
    captured = {}

    def fake_run_loop(single_turn=False):
        captured["messages"] = list(agent.messages)
        return "done"

    def fake_log_outcome():
        pass

    def fake_archive():
        pass

    monkeypatch.setattr(agent, "_run_loop", fake_run_loop)
    monkeypatch.setattr(agent, "_log_session_outcome", fake_log_outcome)
    monkeypatch.setattr(agent, "_archive_session", fake_archive)
    monkeypatch.setattr(agent, "_pin_pr_body", lambda msg: None)
    monkeypatch.setattr(agent, "_detect_user_correction", lambda msg: None)

    agent.run("implement the feature")

    assert captured.get("messages"), "messages should not be empty"
    first_content = captured["messages"][0]["content"]
    assert "<session-handoff>" in first_content
    assert "Handoff content" in first_content
    assert "implement the feature" in first_content


def test_seed_not_injected_on_casual_path(tmp_path, monkeypatch):
    """On casual chat path (classify returned text), seed is NOT injected."""
    from hermit_agent.llm_client import LLMResponse

    handoffs_dir = tmp_path / ".hermit" / "handoffs"
    _write_handoff(handoffs_dir, "auto-compact-20260101-120000.md", "# Handoff")

    agent = _make_agent(tmp_path, max_context_tokens=32000)
    # Override classify to return a casual response (not NEED_TOOLS)
    agent.llm.chat.return_value = LLMResponse(content="Sure, the answer is 42.", tool_calls=[])


    def fake_log_outcome():
        pass

    monkeypatch.setattr(agent, "_log_session_outcome", fake_log_outcome)
    monkeypatch.setattr(agent, "_pin_pr_body", lambda msg: None)
    monkeypatch.setattr(agent, "_detect_user_correction", lambda msg: None)

    result = agent.run("what is 6 times 7?")
    # Should return classify response directly (no _run_loop)
    assert "<session-handoff>" not in result


def test_seed_truncated_at_2000_chars(tmp_path, monkeypatch):
    """Handoff content exceeding 2000 chars is capped with truncation marker."""
    handoffs_dir = tmp_path / ".hermit" / "handoffs"
    long_content = "x" * 3000
    _write_handoff(handoffs_dir, "auto-compact-20260101-120000.md", long_content)

    agent = _make_agent(tmp_path, max_context_tokens=32000)

    captured = {}

    def fake_run_loop(single_turn=False):
        captured["messages"] = list(agent.messages)
        return "done"

    monkeypatch.setattr(agent, "_run_loop", fake_run_loop)
    monkeypatch.setattr(agent, "_log_session_outcome", lambda: None)
    monkeypatch.setattr(agent, "_archive_session", lambda: None)
    monkeypatch.setattr(agent, "_pin_pr_body", lambda msg: None)
    monkeypatch.setattr(agent, "_detect_user_correction", lambda msg: None)

    agent.run("do something")

    first_content = captured["messages"][0]["content"]
    assert "[...handoff truncated...]" in first_content
    # The handoff block should not exceed 2000 chars of content
    # (plus wrapper tags)
    handoff_start = first_content.index("<session-handoff>") + len("<session-handoff>\n")
    handoff_end = first_content.index("\n</session-handoff>")
    handoff_body = first_content[handoff_start:handoff_end]
    assert len(handoff_body) <= 2000 + len("\n\n[...handoff truncated...]") + 5


def test_seed_skipped_when_small_context(tmp_path, monkeypatch):
    """max_context_tokens < 16000 → seed injection skipped."""
    handoffs_dir = tmp_path / ".hermit" / "handoffs"
    _write_handoff(handoffs_dir, "auto-compact-20260101-120000.md", "# Handoff")

    agent = _make_agent(tmp_path, max_context_tokens=8000)

    captured = {}

    def fake_run_loop(single_turn=False):
        captured["messages"] = list(agent.messages)
        return "done"

    monkeypatch.setattr(agent, "_run_loop", fake_run_loop)
    monkeypatch.setattr(agent, "_log_session_outcome", lambda: None)
    monkeypatch.setattr(agent, "_archive_session", lambda: None)
    monkeypatch.setattr(agent, "_pin_pr_body", lambda msg: None)
    monkeypatch.setattr(agent, "_detect_user_correction", lambda msg: None)

    agent.run("do something")

    first_content = captured["messages"][0]["content"]
    assert "<session-handoff>" not in first_content


def test_seed_skipped_when_env_disabled(tmp_path, monkeypatch):
    """HERMIT_SEED_HANDOFF=0 disables seed injection."""
    handoffs_dir = tmp_path / ".hermit" / "handoffs"
    _write_handoff(handoffs_dir, "auto-compact-20260101-120000.md", "# Handoff")

    agent = _make_agent(tmp_path, max_context_tokens=32000)

    monkeypatch.setenv("HERMIT_SEED_HANDOFF", "0")

    captured = {}

    def fake_run_loop(single_turn=False):
        captured["messages"] = list(agent.messages)
        return "done"

    monkeypatch.setattr(agent, "_run_loop", fake_run_loop)
    monkeypatch.setattr(agent, "_log_session_outcome", lambda: None)
    monkeypatch.setattr(agent, "_archive_session", lambda: None)
    monkeypatch.setattr(agent, "_pin_pr_body", lambda msg: None)
    monkeypatch.setattr(agent, "_detect_user_correction", lambda msg: None)

    agent.run("do something")

    first_content = captured["messages"][0]["content"]
    assert "<session-handoff>" not in first_content


def test_seed_marks_consumed(tmp_path, monkeypatch):
    """After seed injection, the handoff file is marked as consumed."""
    handoffs_dir = tmp_path / ".hermit" / "handoffs"
    _write_handoff(handoffs_dir, "auto-compact-20260101-120000.md", "# Handoff")

    agent = _make_agent(tmp_path, max_context_tokens=32000)

    monkeypatch.setattr(agent, "_run_loop", lambda single_turn=False: "done")
    monkeypatch.setattr(agent, "_log_session_outcome", lambda: None)
    monkeypatch.setattr(agent, "_archive_session", lambda: None)
    monkeypatch.setattr(agent, "_pin_pr_body", lambda msg: None)
    monkeypatch.setattr(agent, "_detect_user_correction", lambda msg: None)

    agent.run("do something")

    consumed = _load_consumed(handoffs_dir)
    assert "auto-compact-20260101-120000.md" in consumed


def test_seed_not_injected_twice(tmp_path, monkeypatch):
    """Second call to run() on same agent does not inject seed again."""
    handoffs_dir = tmp_path / ".hermit" / "handoffs"
    _write_handoff(handoffs_dir, "auto-compact-20260101-120000.md", "# Handoff")

    agent = _make_agent(tmp_path, max_context_tokens=32000)

    all_messages = []

    def fake_run_loop(single_turn=False):
        all_messages.extend(list(agent.messages))
        return "done"

    monkeypatch.setattr(agent, "_run_loop", fake_run_loop)
    monkeypatch.setattr(agent, "_log_session_outcome", lambda: None)
    monkeypatch.setattr(agent, "_archive_session", lambda: None)
    monkeypatch.setattr(agent, "_pin_pr_body", lambda msg: None)
    monkeypatch.setattr(agent, "_detect_user_correction", lambda msg: None)

    # First run — seed injected, context_injected set True
    agent.run("first message")
    # Simulate second turn: context already injected
    agent.messages = []  # reset messages but keep _context_injected=True
    # classify won't be called since _context_injected is True after first run
    agent.run("second message")

    # Count session-handoff occurrences
    combined = " ".join(m["content"] for m in all_messages)
    count = combined.count("<session-handoff>")
    assert count == 1, f"expected 1 seed injection, got {count}"
