"""HermitAgent MCP Server — exposes HermitAgent as an MCP tool for Claude Code.

Thin MCP → Gateway REST proxy:
    MCP tool call → AI Gateway REST API → SSE events → hermit-channel push

Transport: Python MCP SDK (mcp package) — stdio or streamable-http

Bidirectional protocol:
    1. run_task(task, cwd) → {status:"waiting", task_id, question, options}
                           or {status:"done", result}
    2. reply_task(task_id, message) → repeats the same format
    3. When HermitAgent calls ask_user_question, the question is forwarded to Claude Code
    4. Claude Code replies via reply_task → HermitAgent resumes

Environment variables:
    HERMIT_MCP_GATEWAY_URL     Gateway REST URL (default: http://127.0.0.1:8765)
    HERMIT_MCP_GATEWAY_API_KEY Gateway auth key

Log monitoring:
    tail -f ~/.hermit/mcp_server.log
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import httpx
from pathlib import Path
from typing import Any

from .channels_core.event_adapters import channel_action_from_sse_event
from .mcp_paths import resolve_git_cwd
from .mcp_results import (
    HEAD_SIZE,
    RESULT_CAP,
    TAIL_SIZE,
    result_to_text as _result_to_text,
    truncate_result as _truncate_result,
)
from .mcp_schema import DEFAULT_MODEL as _DEFAULT_MODEL
from .mcp_schema import PROTOCOL_VERSION, SERVER_INFO, TOOLS
from .mcp_channel import (
    _notify_channel,
    _notify_done,
    _notify_error,
    _notify_reply,
    _notify_running,
    _set_active_session,
)
from .mcp_sse_bridge import _SSEBridge as _BaseSSEBridge


def _resolve_git_cwd(cwd: str) -> str:
    return resolve_git_cwd(cwd, log_fn=_log)

# ── File logger ───────────────────────────────────────────────────────────────

_LOG_PATH = os.path.expanduser("~/.hermit/mcp_server.log")


def _init_log() -> None:
    os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)


def _log(line: str) -> None:
    ts = time.strftime("%H:%M:%S")
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {line}\n")
            f.flush()
    except Exception:
        pass


_NOTIFY_TIMEOUT = 10       # seconds


# meta keys policy:
#   - "source": NEVER include — CC auto-sets <channel source="..."> from the
#     registered MCP server name (so notifications/claude/channel from this
#     server appear as <channel source="hermit-channel">). Including a custom
#     "source" field collided with that auto-tag and CC silently dropped the
#     frame (root cause of the original "channel not delivering" bug, paired
#     with the contextvar leak fix above).
#   - "type": renamed to "kind" — "type" was treated as a reserved field.
#   - The remaining keys (task_id, kind, question/options/message) become
#     XML attributes on the <channel> tag in the Claude message stream.

# ── Gateway client ────────────────────────────────────────────────────────────

_GATEWAY_URL: str | None = None
_GATEWAY_API_KEY: str | None = None
_GATEWAY_CLIENT: httpx.Client | None = None

# SSE bridge registry: task_id → _SSEBridge
_sse_bridges: dict[str, _SSEBridge] = {}
_sse_bridges_lock = threading.Lock()

# Healthcheck state
_consecutive_failures = 0
_MAX_CONSECUTIVE_FAILURES = 3
_last_health_check = 0.0
_HEALTH_CHECK_INTERVAL = 120.0


def _init_gateway_client() -> None:
    """Initialize Gateway client from config/env vars."""
    global _GATEWAY_URL, _GATEWAY_API_KEY, _GATEWAY_CLIENT

    from hermit_agent.config import load_settings
    cfg = load_settings()

    # MCP-specific env vars take priority → config.py settings fallback
    _GATEWAY_URL = os.environ.get("HERMIT_MCP_GATEWAY_URL") or cfg.get("gateway_url", "http://127.0.0.1:8765")
    _GATEWAY_API_KEY = os.environ.get("HERMIT_MCP_GATEWAY_API_KEY") or cfg.get("gateway_api_key") or None
    if not _GATEWAY_API_KEY:
        _log("[gateway] API key not set — using unauthenticated mode")
    _GATEWAY_CLIENT = httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0))


def _gateway_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if _GATEWAY_API_KEY:
        headers["Authorization"] = f"Bearer {_GATEWAY_API_KEY}"
    return headers


def _gateway_health_check(force: bool = False) -> bool:
    global _consecutive_failures, _last_health_check

    now = time.time()
    if not force and now - _last_health_check < 10.0:
        return _consecutive_failures < _MAX_CONSECUTIVE_FAILURES

    _last_health_check = now
    if not _GATEWAY_URL or not _GATEWAY_CLIENT:
        return False

    try:
        r = _GATEWAY_CLIENT.get(f"{_GATEWAY_URL}/health", timeout=5.0)
        is_healthy = r.status_code == 200
        if is_healthy:
            _consecutive_failures = 0
        else:
            _consecutive_failures += 1
        return is_healthy
    except Exception as e:
        _consecutive_failures += 1
        _log(f"[gateway] health check failed: {e}")
        return False


class _SSEBridge(_BaseSSEBridge):
    """mcp_server-local wrapper preserving existing test patch points."""

    def __init__(self, task_id: str, client: httpx.Client):
        def _dispatch_action(task_id: str, action) -> None:
            if action.kind == "prompt":
                _notify_channel(task_id, action.question, list(action.options))
            elif action.kind == "done":
                _notify_done(task_id, action.message[:200] if action.message else None)
            elif action.kind == "error":
                _notify_error(task_id, action.message)
            elif action.kind == "running":
                _notify_running(task_id)

        def _cleanup_with_lock(task_id: str) -> None:
            with _sse_bridges_lock:
                _sse_bridges.pop(task_id, None)

        super().__init__(
            task_id=task_id,
            client=client,
            gateway_url=_GATEWAY_URL,
            gateway_api_key=_GATEWAY_API_KEY,
            log_fn=_log,
            on_action=_dispatch_action,
            on_cleanup=_cleanup_with_lock,
        )

    def _handle_sse_event(self, event: dict) -> None:
        event_type = event.get("type", "")
        self._bridge_log(f"event: {event_type}")

        action = channel_action_from_sse_event(event)
        if action is None:
            return
        if action.kind == "prompt":
            _notify_channel(self.task_id, action.question, list(action.options))
        elif action.kind == "done":
            _notify_done(self.task_id, action.message[:200] if action.message else None)
        elif action.kind == "error":
            _notify_error(self.task_id, action.message)
        elif action.kind == "running":
            _notify_running(self.task_id)


def _start_sse_bridge(task_id: str) -> _SSEBridge:
    """Start SSE bridge. Returns the bridge instance."""
    if not _GATEWAY_CLIENT:
        _init_gateway_client()

    bridge = _SSEBridge(task_id, _GATEWAY_CLIENT)
    bridge.start()

    with _sse_bridges_lock:
        _sse_bridges[task_id] = bridge

    return bridge


def _cleanup_sse_bridge(task_id: str) -> None:
    """Clean up SSE bridge."""
    with _sse_bridges_lock:
        bridge = _sse_bridges.pop(task_id, None)

    if bridge:
        bridge.shutdown()


def _shutdown_all_bridges() -> None:
    """Shut down all SSE bridges (called on process exit)."""
    with _sse_bridges_lock:
        task_ids = list(_sse_bridges.keys())

    for tid in task_ids:
        _cleanup_sse_bridge(tid)

    _log(f"[shutdown] {_sse_bridges} SSE bridges cleaned up" if task_ids else "[shutdown] no active SSE bridges")


def _build_mcp_app(host: str = "0.0.0.0", port: int = 3737) -> "FastMCP":
    """Create a FastMCP app and register the 4 tools."""
    from mcp.server.fastmcp import FastMCP

    mcp_app = FastMCP(
        "hermit-channel",
        host=host,
        port=port,
    )

    original_create_init = mcp_app._mcp_server.create_initialization_options

    def _create_init_with_channel_caps(**kw):
        kw.setdefault(
            "experimental_capabilities",
            {"claude/channel": {}, "claude/channel/permission": {}},
        )
        return original_create_init(**kw)

    mcp_app._mcp_server.create_initialization_options = _create_init_with_channel_caps

    @mcp_app.tool()
    async def register_task(task_id: str) -> str:
        """Register a task_id. Stdio per-session makes per-port routing unnecessary;
        this exists for backward compatibility with .claude/commands/*-hermit.md."""
        _log(f"[register_task] task_id={task_id[:8]}")
        _set_active_session(mcp_app.get_context().session, asyncio.get_running_loop())
        return f"registered:{task_id}"

    @mcp_app.tool(description=TOOLS[0]["description"])
    async def run_task(
        task: str,
        cwd: str,
        model: str = "",
        max_turns: int = 200,
        background: bool = False,
    ) -> str:
        """Run a coding task using a local LLM (delegated to Gateway)."""
        _set_active_session(mcp_app.get_context().session, asyncio.get_running_loop())
        _log(f"[req] run_task cwd={cwd} bg={background} model={model or 'default'}")

        if not _gateway_health_check():
            return _result_to_text({
                "status": "error",
                "message": "AI Gateway is not responding. Make sure the Gateway is running.",
            })

        try:
            resolved_cwd = _resolve_git_cwd(cwd)

            payload: dict[str, Any] = {
                "task": task,
                "cwd": resolved_cwd,
                "max_turns": max_turns,
            }
            if model:
                payload["model"] = model

            r = _GATEWAY_CLIENT.post(
                f"{_GATEWAY_URL}/tasks",
                json=payload,
                headers=_gateway_headers(),
                timeout=30.0,
            )
            r.raise_for_status()
            data = r.json()

            task_id = data.get("task_id", "")
            status = data.get("status", "running")

            if status == "done" and task_id == "instant":
                result = data.get("result", "")
                truncated, meta = _truncate_result(result)
                payload = {"status": "done", "result": truncated}
                if meta:
                    payload["_truncation"] = meta
                return _result_to_text(payload)

            if status == "running":
                _start_sse_bridge(task_id)
                return _result_to_text({"status": "running", "task_id": task_id})

            if status == "error":
                message = data.get("message", "")
                _notify_error(task_id, message)
                return _result_to_text({"status": "error", "message": message})

            return _result_to_text(data)

        except httpx.HTTPStatusError as e:
            _log(f"[err] run_task: {e}")
            return _result_to_text({"status": "error", "message": f"Gateway HTTP error: {e.response.status_code}"})
        except httpx.RequestError as e:
            _log(f"[err] run_task: {e}")
            return _result_to_text({"status": "error", "message": f"Gateway communication error: {e}"})

    @mcp_app.tool(description=TOOLS[1]["description"])
    async def reply_task(task_id: str, message: str) -> str:
        """Send a reply to HermitAgent."""
        _set_active_session(mcp_app.get_context().session, asyncio.get_running_loop())
        _log(f"[req] reply_task task_id={task_id} msg={message[:60]}")

        try:
            r = _GATEWAY_CLIENT.post(
                f"{_GATEWAY_URL}/tasks/{task_id}/reply",
                json={"message": message},
                headers=_gateway_headers(),
                timeout=30.0,
            )
            r.raise_for_status()

            _notify_reply(task_id, message)
            return _result_to_text({"status": "running", "task_id": task_id})

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return _result_to_text({"status": "not_found", "message": f"Task not found: {task_id}"})
            _log(f"[err] reply_task: {e}")
            return _result_to_text({"status": "error", "message": f"Gateway HTTP error: {e.response.status_code}"})
        except httpx.RequestError as e:
            _log(f"[err] reply_task: {e}")
            return _result_to_text({"status": "error", "message": f"Gateway communication error: {e}"})

    @mcp_app.tool(description=TOOLS[2]["description"])
    async def check_task(task_id: str, full: bool = False) -> str:
        """Check the current status of a background task."""
        _set_active_session(mcp_app.get_context().session, asyncio.get_running_loop())
        _log(f"[req] check_task task_id={task_id} full={full}")

        try:
            r = _GATEWAY_CLIENT.get(
                f"{_GATEWAY_URL}/tasks/{task_id}",
                headers=_gateway_headers(),
                timeout=10.0,
            )
            r.raise_for_status()
            data = r.json()

            status = data.get("status")
            if status == "waiting":
                question = data.get("question", "")
                options = data.get("options", [])
                _notify_channel(task_id, question, options)

            if status == "done":
                result = data.get("result", "")
                if not full:
                    truncated, meta = _truncate_result(result)
                    data["result"] = truncated
                    if meta:
                        data["_truncation"] = meta

            return _result_to_text(data)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return _result_to_text({"status": "not_found", "message": f"Task not found: {task_id}"})
            _log(f"[err] check_task: {e}")
            return _result_to_text({"status": "error", "message": f"Gateway HTTP error: {e.response.status_code}"})
        except httpx.RequestError as e:
            _log(f"[err] check_task: {e}")
            return _result_to_text({"status": "error", "message": f"Gateway communication error: {e}"})

    @mcp_app.tool(description=TOOLS[3]["description"])
    async def cancel_task(task_id: str) -> str:
        """Cancel a running task."""
        _log(f"[req] cancel_task task_id={task_id}")

        try:
            r = _GATEWAY_CLIENT.delete(
                f"{_GATEWAY_URL}/tasks/{task_id}",
                headers=_gateway_headers(),
                timeout=10.0,
            )
            r.raise_for_status()

            _cleanup_sse_bridge(task_id)
            return _result_to_text({"status": "cancelled", "task_id": task_id})

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return _result_to_text({"status": "not_found", "message": f"Task not found: {task_id}"})
            _log(f"[err] cancel_task: {e}")
            return _result_to_text({"status": "error", "message": f"Gateway HTTP error: {e.response.status_code}"})
        except httpx.RequestError as e:
            _log(f"[err] cancel_task: {e}")
            return _result_to_text({"status": "error", "message": f"Gateway communication error: {e}"})

    return mcp_app


# ── Entry points ───────────────────────────────────────────────────────────────

def main_http(port: int = 3737) -> None:
    import atexit

    _init_log()
    _log(f"=== HermitAgent MCP Server v0.5.0 (HTTP mode :{port}, Gateway proxy) started ===")
    print(f"[hermit_agent-mcp] MCP HTTP listening on 0.0.0.0:{port}/mcp (Gateway proxy)", file=sys.stderr, flush=True)

    _init_gateway_client()
    if not _gateway_health_check():
        _log("[gateway] WARNING: Gateway health check failed on startup")

    atexit.register(_shutdown_all_bridges)

    mcp_app = _build_mcp_app(host="0.0.0.0", port=port)
    mcp_app.run(transport="streamable-http")


def main() -> None:
    import atexit

    _init_log()
    _log("=== HermitAgent MCP Server v0.5.0 (stdio mode, Gateway proxy) started ===")
    print("HermitAgent MCP Server v0.5.0 started (Gateway proxy)", file=sys.stderr, flush=True)

    _init_gateway_client()
    if not _gateway_health_check():
        _log("[gateway] WARNING: Gateway health check failed on startup")

    atexit.register(_shutdown_all_bridges)

    mcp_app = _build_mcp_app()
    mcp_app.run(transport="stdio")


if __name__ == "__main__":
    # --http [PORT] flag: Docker/persistent HTTP mode
    if "--http" in sys.argv:
        idx = sys.argv.index("--http")
        _port = 3737
        if idx + 1 < len(sys.argv) and sys.argv[idx + 1].isdigit():
            _port = int(sys.argv[idx + 1])
        main_http(_port)
    else:
        main()
