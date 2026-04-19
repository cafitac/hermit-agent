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
import json
import os
import sys
import threading
import time
import httpx
from pathlib import Path
from typing import Any

from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCNotification

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


# ── stdio channel notification (native MCP) ───────────────────────────────────

# Module-level globals (NOT ContextVar) so notifications fired from the SSE
# bridge background thread can find the active session/loop. ContextVar values
# do NOT propagate to threads spawned outside the asyncio task context, which
# silently dropped every channel notification before this fix.
_current_session = None  # type: ignore[assignment]
_current_loop = None     # type: ignore[assignment]
_session_lock = threading.Lock()


def _set_active_session(session, loop) -> None:
    """Record the active stdio MCP session + asyncio loop for cross-thread
    channel notifications. Called from every MCP tool handler."""
    global _current_session, _current_loop
    with _session_lock:
        _current_session = session
        _current_loop = loop


async def _send_channel_notification(session, content: str, meta: dict) -> None:
    """Emit a `notifications/claude/channel` frame over the active stdio session.

    Uses the private `_write_stream` escape hatch because `ServerNotification`
    is a closed `RootModel` union in mcp>=1.27 and `send_notification()` cannot
    deliver custom notification methods.
    """
    notif = JSONRPCNotification(
        jsonrpc="2.0",
        method="notifications/claude/channel",
        params={"content": content, "meta": meta},
    )
    _log(f"[channel] -> write_stream.send type={meta.get('kind')} task={str(meta.get('task_id',''))[:8]}")
    await session._write_stream.send(SessionMessage(message=JSONRPCMessage(notif)))
    _log(f"[channel] <- write_stream.send ok type={meta.get('kind')}")


def _fire_channel_notification_sync(content: str, meta: dict) -> None:
    with _session_lock:
        session = _current_session
        loop = _current_loop
    if session is None or loop is None:
        _log("[channel] no active session/loop — notification dropped")
        return
    _log(f"[channel] scheduling coroutine type={meta.get('kind')} task={str(meta.get('task_id',''))[:8]}")
    try:
        fut = asyncio.run_coroutine_threadsafe(
            _send_channel_notification(session, content, meta),
            loop,
        )
        fut.result(timeout=5)
        _log(f"[channel] coroutine completed type={meta.get('kind')}")
    except Exception as e:
        _log(f"[channel] send failed: {e}")


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

def _notify_channel(task_id: str, question: str, options: list[str]) -> None:
    meta = {"task_id": task_id, "kind": "waiting"}
    if options:
        meta["options"] = ",".join(options)
    _fire_channel_notification_sync(question, meta)


def _notify_done(task_id: str, message: str | None = None) -> None:
    meta = {"task_id": task_id, "kind": "done"}
    _fire_channel_notification_sync(message or "task done", meta)


def _notify_reply(task_id: str, message: str) -> None:
    meta = {"task_id": task_id, "kind": "reply"}
    _fire_channel_notification_sync(message, meta)


def _notify_error(task_id: str, message: str) -> None:
    meta = {"task_id": task_id, "kind": "error"}
    _fire_channel_notification_sync(message, meta)


def _notify_running(task_id: str) -> None:
    _fire_channel_notification_sync(
        "task running",
        {"task_id": task_id, "kind": "running"},
    )


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


# ── SSE → hermit-channel bridge ──────────────────────────────────────────────

class _SSEBridge:
    """Consume the Gateway SSE stream and bridge events to hermit-channel.

    One bridge instance per task, running on a background thread.
    Auto-cleans on completion or error.
    """

    def __init__(self, task_id: str, client: httpx.Client):
        self.task_id = task_id
        self.client = client
        self.shutdown_event = threading.Event()
        self.thread: threading.Thread | None = None
        self._last_event_time = time.time()

    def _bridge_log(self, msg: str) -> None:
        _log(f"[sse-bridge {self.task_id[:8]}] {msg}")

    def start(self) -> None:
        self.thread = threading.Thread(
            target=self._consume_sse,
            name=f"sse-bridge-{self.task_id[:8]}",
            daemon=True,
        )
        self.thread.start()
        self._bridge_log("started")

    def shutdown(self) -> None:
        self.shutdown_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5.0)
            if self.thread.is_alive():
                self._bridge_log("thread did not exit gracefully")
        self._bridge_log("shutdown")

    def _consume_sse(self) -> None:
        url = f"{_GATEWAY_URL}/tasks/{self.task_id}/stream"
        headers = {}
        if _GATEWAY_API_KEY:
            headers["Authorization"] = f"Bearer {_GATEWAY_API_KEY}"

        try:
            with self.client.stream("GET", url, headers=headers, timeout=None) as resp:
                resp.raise_for_status()

                for line in resp.iter_lines():
                    if self.shutdown_event.is_set():
                        break

                    self._last_event_time = time.time()

                    if not line:
                        continue

                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            event = json.loads(data_str)
                            self._handle_sse_event(event)
                        except json.JSONDecodeError:
                            pass

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                self._bridge_log("task not found (404) -- cleanup")
            else:
                self._bridge_log(f"http error: {e}")
        except Exception as e:
            if not self.shutdown_event.is_set():
                self._bridge_log(f"error: {e}")

        # Auto-cleanup on exit
        with _sse_bridges_lock:
            _sse_bridges.pop(self.task_id, None)

    def _handle_sse_event(self, event: dict) -> None:
        event_type = event.get("type", "")
        self._bridge_log(f"event: {event_type}")

        if event_type == "waiting":
            question = event.get("question", "")
            options = event.get("options", [])
            _notify_channel(self.task_id, question, options)

        elif event_type == "permission_ask":
            question = event.get("question", "")
            options = event.get("options", [])
            _notify_channel(self.task_id, question, options)

        elif event_type == "done":
            result = event.get("result", "")
            _notify_done(self.task_id, result[:200] if result else None)

        elif event_type == "error":
            message = event.get("message", "")
            _notify_error(self.task_id, message)

        elif event_type == "cancelled":
            message = event.get("message", "Task cancelled")
            _notify_error(self.task_id, message)

        elif event_type == "reply_ack":
            _notify_running(self.task_id)

        # progress, tool_result, streaming, stream_end, tool_use, status: no channel notification


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


# ── cwd preprocessing ─────────────────────────────────────────────────────────

def _resolve_git_cwd(cwd: str) -> str:
    """If cwd is not a git repo, search subdirectories for one and return it."""
    import subprocess

    def _is_git_repo(path: str) -> bool:
        try:
            r = subprocess.run(
                ["git", "-C", path, "rev-parse", "--git-dir"],
                capture_output=True, timeout=5,
            )
            return r.returncode == 0
        except Exception:
            return False

    if _is_git_repo(cwd):
        return cwd

    try:
        candidates = [
            str(p) for p in Path(cwd).iterdir()
            if p.is_dir() and not p.name.startswith(".") and _is_git_repo(str(p))
        ]
    except Exception:
        candidates = []

    if len(candidates) == 1:
        _log(f"  i cwd '{cwd}' is not a git repo -> auto-replacing with '{candidates[0]}'")
        return candidates[0]

    if len(candidates) > 1:
        short = [Path(c).name for c in candidates[:5]]
        more = f" + {len(candidates)-5} more" if len(candidates) > 5 else ""
        _log(f"  ! {len(candidates)} git repos found under cwd '{cwd}' -- {short}{more}")
    else:
        _log(f"  ! no git repo found in '{cwd}' or its subdirectories")

    return cwd


# ── Constants ─────────────────────────────────────────────────────────────────

SERVER_INFO = {"name": "hermit_agent", "version": "0.2.0"}
PROTOCOL_VERSION = "2024-11-05"
_DEFAULT_MODEL = "qwen3-coder:30b"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "run_task",
        "description": (
            "Run a coding task using a local LLM (default: qwen3-coder:30b).\n"
            "If background=true, immediately returns {status:'running', task_id} and runs in the background.\n"
            "Check completion with check_task(task_id).\n"
            "Return values:\n"
            '  {status:"running", task_id} — running in background (when background=true).\n'
            '  {status:"waiting", task_id, question, options} — HermitAgent is asking a question. '
            "Reply with reply_task(task_id, message).\n"
            '  {status:"done", result} — task completed.'
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Task description to execute"},
                "cwd": {"type": "string", "description": "Absolute path of working directory"},
                "model": {"type": "string", "description": f"Model to use (default: {_DEFAULT_MODEL})"},
                "max_turns": {"type": "integer", "description": "Maximum number of turns (default: 200)"},
                "background": {"type": "boolean", "description": "If true, return task_id immediately and run in background (default: false)"},
            },
            "required": ["task", "cwd"],
        },
    },
    {
        "name": "reply_task",
        "description": (
            "Send a reply to HermitAgent when run_task returned {status:\"waiting\"}.\n"
            "Return format is the same as run_task (waiting or done)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task_id returned by run_task"},
                "message": {"type": "string", "description": "Reply to send to HermitAgent"},
            },
            "required": ["task_id", "message"],
        },
    },
    {
        "name": "check_task",
        "description": (
            "Check the current status of a background task (use after run_task with background=true).\n"
            "Return values:\n"
            '  {status:"running"} — still running.\n'
            '  {status:"waiting", question, options} — user input required.\n'
            '  {status:"done", result} — completed.\n'
            '  {status:"not_found"} — task_id not found (already completed and removed).\n'
            "Use full=true to retrieve the complete result without truncation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task_id returned by run_task"},
                "full": {
                    "type": "boolean",
                    "description": "If true, return the complete result without truncation (default: false).",
                    "default": False,
                },
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "cancel_task",
        "description": "Cancel a running task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task_id to cancel"},
            },
            "required": ["task_id"],
        },
    },
]


# ── Result truncation ─────────────────────────────────────────────────────────

RESULT_CAP = 4000
HEAD_SIZE = 2000
TAIL_SIZE = 1000


def _truncate_result(result: str, cap: int = RESULT_CAP) -> tuple[str, dict]:
    """Truncate long result strings with head+tail preservation.

    Returns (truncated_text, metadata_dict). metadata is empty when no truncation applied.
    Non-string values are returned unchanged (see test_non_string_result_unchanged).
    Only "done" status carries a long result — all other paths (running, error, reply) are exempt.
    """
    if not isinstance(result, str):
        return result, {}
    if len(result) <= cap:
        return result, {}
    head = result[:HEAD_SIZE]
    tail = result[-TAIL_SIZE:]
    omitted = len(result) - HEAD_SIZE - TAIL_SIZE
    notice = (
        f"\n\n[... {omitted} chars omitted. "
        f"Use check_task(task_id, full=true) for full content ...]\n\n"
    )
    truncated = head + notice + tail
    metadata = {
        "truncated": True,
        "original_length": len(result),
        "head_size": HEAD_SIZE,
        "tail_size": TAIL_SIZE,
    }
    return truncated, metadata


# ── MCP SDK Server ─────────────────────────────────────────────────────────────

def _result_to_text(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False)


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
