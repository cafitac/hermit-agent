"""Test HermitAgent MCP Server thin proxy.

Verify Gateway REST proxy + SSE bridge + hermit-channel notifications.
Actual AgentLoop execution is handled separately in integration tests.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── _result_to_text ──────────────────────────────────────────────────────────


def test_result_to_text():
    """Convert dict result to JSON string."""
    from hermit_agent.mcp_server import _result_to_text

    result = _result_to_text({"status": "done", "result": "Task complete"})
    parsed = json.loads(result)
    assert parsed["status"] == "done"
    assert parsed["result"] == "Task complete"


def test_result_to_text_korean_preserved():
    """Ensure Korean characters are preserved (ensure_ascii=False)."""
    from hermit_agent.mcp_server import _result_to_text

    result = _result_to_text({"status": "error", "message": "Working directory not found"})
    assert "not found" in result


# ── TOOLS schema ─────────────────────────────────────────────────────────────


def test_tools_schema_contains_four_tools():
    """Four tools (run_task, reply_task, check_task, cancel_task) are defined."""
    from hermit_agent.mcp_server import TOOLS

    names = [t["name"] for t in TOOLS]
    assert names == ["run_task", "reply_task", "check_task", "cancel_task"]


def test_run_task_schema_has_required_fields():
    """task, cwd are required in run_task inputSchema."""
    from hermit_agent.mcp_server import TOOLS

    run_task = next(t for t in TOOLS if t["name"] == "run_task")
    schema = run_task["inputSchema"]
    assert "task" in schema["required"]
    assert "cwd" in schema["required"]
    assert "background" in schema["properties"]


# ── SSE Bridge Event Mapping ───────────────────────────────────────────────────


def test_sse_bridge_waiting_event():
    """SSE 'waiting' event → call _notify_channel."""
    from unittest.mock import patch
    from hermit_agent.mcp_server import _SSEBridge
    import httpx

    bridge = _SSEBridge("test-task-1", httpx.Client())

    with patch("hermit_agent.mcp_server._notify_channel") as mock_notify:
        bridge._handle_sse_event({
            "type": "waiting",
            "question": "Continue?",
            "options": ["Yes", "No"],
        })
        mock_notify.assert_called_once_with(
            "test-task-1",
            "Continue?",
            ["Yes", "No"],
            prompt_kind="waiting",
            tool_name="ask",
            method="",
        )


def test_sse_bridge_done_event():
    """SSE 'done' event → call _notify_done."""
    from unittest.mock import patch
    from hermit_agent.mcp_server import _SSEBridge
    import httpx

    bridge = _SSEBridge("test-task-2", httpx.Client())

    with patch("hermit_agent.mcp_server._notify_done") as mock_done:
        bridge._handle_sse_event({"type": "done", "result": "All tasks complete"})
        mock_done.assert_called_once_with("test-task-2", "All tasks complete")


def test_sse_bridge_error_event():
    """SSE 'error' event → call _notify_error."""
    from unittest.mock import patch
    from hermit_agent.mcp_server import _SSEBridge
    import httpx

    bridge = _SSEBridge("test-task-3", httpx.Client())

    with patch("hermit_agent.mcp_server._notify_error") as mock_error:
        bridge._handle_sse_event({"type": "error", "message": "LLM call failed"})
        mock_error.assert_called_once_with("test-task-3", "LLM call failed")


def test_sse_bridge_permission_ask_event():
    """SSE 'permission_ask' event → call _notify_channel (same as waiting)."""
    from unittest.mock import patch
    from hermit_agent.mcp_server import _SSEBridge
    import httpx

    bridge = _SSEBridge("test-task-4", httpx.Client())

    with patch("hermit_agent.mcp_server._notify_channel") as mock_notify:
        bridge._handle_sse_event({
            "type": "permission_ask",
            "question": "[Permission request] bash",
            "options": ["Yes", "No"],
        })
        mock_notify.assert_called_once_with(
            "test-task-4",
            "[Permission request] bash",
            ["Yes", "No"],
            prompt_kind="permission_ask",
            tool_name="bash",
            method="",
        )


def test_sse_bridge_reply_ack_event():
    """SSE 'reply_ack' event → call _notify_running."""
    from unittest.mock import patch
    from hermit_agent.mcp_server import _SSEBridge
    import httpx

    bridge = _SSEBridge("test-task-5", httpx.Client())

    with patch("hermit_agent.mcp_server._notify_running") as mock_running:
        bridge._handle_sse_event({"type": "reply_ack", "message": "reply received"})
        mock_running.assert_called_once_with("test-task-5")


def test_sse_bridge_cancelled_event():
    """SSE 'cancelled' event → call _notify_error."""
    from unittest.mock import patch
    from hermit_agent.mcp_server import _SSEBridge
    import httpx

    bridge = _SSEBridge("test-task-6", httpx.Client())

    with patch("hermit_agent.mcp_server._notify_error") as mock_error:
        bridge._handle_sse_event({"type": "cancelled", "message": "Task cancelled"})
        mock_error.assert_called_once_with("test-task-6", "Task cancelled")


def test_sse_bridge_internal_events_ignored():
    """Internal events such as progress, tool_result, and streaming are ignored."""
    from unittest.mock import patch
    from hermit_agent.mcp_server import _SSEBridge
    import httpx

    bridge = _SSEBridge("test-task-7", httpx.Client())

    with patch("hermit_agent.mcp_server._notify_channel") as mock_ch, \
         patch("hermit_agent.mcp_server._notify_done") as mock_done, \
         patch("hermit_agent.mcp_server._notify_error") as mock_err, \
         patch("hermit_agent.mcp_server._notify_running") as mock_run:

        for event_type in ("progress", "tool_result", "streaming", "stream_end", "tool_use", "status"):
            bridge._handle_sse_event({"type": event_type})

        mock_ch.assert_not_called()
        mock_done.assert_not_called()
        mock_err.assert_not_called()
        mock_run.assert_not_called()


# ── Gateway Client Initialization ────────────────────────────────────────────────


def test_init_gateway_client_from_env():
    """Configure Gateway URL via HERMIT_MCP_GATEWAY_URL env var."""
    from hermit_agent import mcp_server as m

    os.environ["HERMIT_MCP_GATEWAY_URL"] = "http://custom-gateway:9999"
    os.environ["HERMIT_MCP_GATEWAY_API_KEY"] = "test-key-123"
    try:
        m._init_gateway_client()
        assert m._GATEWAY_URL == "http://custom-gateway:9999"
        assert m._GATEWAY_API_KEY == "test-key-123"
        assert m._GATEWAY_CLIENT is not None
    finally:
        del os.environ["HERMIT_MCP_GATEWAY_URL"]
        del os.environ["HERMIT_MCP_GATEWAY_API_KEY"]


def test_gateway_headers_with_api_key():
    """Include Authorization header when API key is set."""
    from hermit_agent import mcp_server as m

    old_key = m._GATEWAY_API_KEY
    try:
        m._GATEWAY_API_KEY = "test-key"
        headers = m._gateway_headers()
        assert headers["Authorization"] == "Bearer test-key"
    finally:
        m._GATEWAY_API_KEY = old_key


def test_gateway_headers_without_api_key():
    """Exclude Authorization header if API key is not set."""
    from hermit_agent import mcp_server as m

    old_key = m._GATEWAY_API_KEY
    try:
        m._GATEWAY_API_KEY = None
        headers = m._gateway_headers()
        assert "Authorization" not in headers
    finally:
        m._GATEWAY_API_KEY = old_key


def test_bootstrap_codex_app_server_writer_from_env_caches_handle(monkeypatch):
    from hermit_agent import mcp_server as m

    calls = {}

    class DummyHandle:
        def close(self):
            calls["closed"] = calls.get("closed", 0) + 1

    monkeypatch.setattr(
        m,
        "bootstrap_codex_app_server_from_env",
        lambda **kwargs: calls.setdefault("handle", DummyHandle()),
    )
    m._CODEX_APP_SERVER_HANDLE = None
    try:
        first = m._bootstrap_codex_app_server_writer_from_env()
        second = m._bootstrap_codex_app_server_writer_from_env()
        assert first is second
        assert first is calls["handle"]
    finally:
        m._CODEX_APP_SERVER_HANDLE = None


def test_cleanup_codex_app_server_writer_closes_handle():
    from hermit_agent import mcp_server as m

    calls = {}

    class DummyHandle:
        def close(self):
            calls["closed"] = calls.get("closed", 0) + 1

    m._CODEX_APP_SERVER_HANDLE = DummyHandle()
    m._cleanup_codex_app_server_writer()

    assert calls["closed"] == 1
    assert m._CODEX_APP_SERVER_HANDLE is None
