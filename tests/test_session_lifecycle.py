"""US-002: Unit tests for SessionLifecycle class."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock


def _make_lifecycle(session_logger=None):
    from hermit_agent.session_lifecycle import SessionLifecycle
    llm = SimpleNamespace(session_logger=session_logger, model="test-model")
    return SessionLifecycle(llm=llm, session_id="abc123")


def _make_mock_logger():
    m = MagicMock()
    m.jsonl_path = "/tmp/fake_session.jsonl"
    return m


def test_log_assistant_text_delegates_to_session_logger():
    mock_logger = _make_mock_logger()
    lc = _make_lifecycle(session_logger=mock_logger)
    lc.log_assistant_text("hello world")
    mock_logger.log_assistant_text.assert_called_once_with("hello world")


def test_log_assistant_text_skips_when_no_logger():
    lc = _make_lifecycle(session_logger=None)
    lc.log_assistant_text("hello")  # should not raise


def test_log_tool_use_delegates():
    mock_logger = _make_mock_logger()
    lc = _make_lifecycle(session_logger=mock_logger)
    tc = SimpleNamespace(id="call_1", name="bash", arguments={"command": "ls"})
    lc.log_tool_use(tc)
    mock_logger.log_tool_use.assert_called_once_with("call_1", "bash", {"command": "ls"})


def test_log_attachment_delegates():
    mock_logger = _make_mock_logger()
    lc = _make_lifecycle(session_logger=mock_logger)
    lc.log_attachment("guardrail_trigger", "", gid="G26", reason="test")
    mock_logger.log_attachment.assert_called_once_with("guardrail_trigger", "", gid="G26", reason="test")


def test_log_session_outcome_delegates_to_log_attachment():
    mock_logger = _make_mock_logger()
    lc = _make_lifecycle(session_logger=mock_logger)
    lc.log_session_outcome(
        model="test-model",
        last_termination="completed",
        compact_count=1,
        test_pass_count=10,
        test_fail_count=2,
        loop_reentry_count=0,
    )
    mock_logger.log_attachment.assert_called_once()
    call_args = mock_logger.log_attachment.call_args
    assert call_args[0][0] == "session_outcome"
    assert call_args[1]["success"] is True
    assert call_args[1]["test_pass_count"] == 10


def test_archive_session_copies_jsonl(tmp_path):
    import os
    session_log = tmp_path / "session.jsonl"
    session_log.write_text('{"type": "start"}')
    mock_logger = _make_mock_logger()
    mock_logger.jsonl_path = str(session_log)
    lc = _make_lifecycle(session_logger=mock_logger)
    # Override metrics dir to tmp_path
    import hermit_agent.session_lifecycle as sl
    old_expanduser = sl.os.path.expanduser
    sl.os.path.expanduser = lambda p: str(tmp_path) if "~" in p else old_expanduser(p)
    try:
        lc.archive_session()
        dest = tmp_path / ".hermit" / "metrics" / "sessions" / "abc123.jsonl"
        assert dest.exists()
    finally:
        sl.os.path.expanduser = old_expanduser
