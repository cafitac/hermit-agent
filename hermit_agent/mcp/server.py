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
import httpx
from ..codex_app_server_bridge import bootstrap_codex_app_server_from_env
from ..channels_core.event_adapters import channel_action_from_sse_event
from .gateway import (
    gateway_headers as _gateway_headers_impl,
    gateway_health_check as _gateway_health_check_impl,
    init_gateway_client as _init_gateway_client_impl,
)
from .paths import resolve_git_cwd
from .results import (
    HEAD_SIZE as HEAD_SIZE,
    RESULT_CAP as RESULT_CAP,
    TAIL_SIZE as TAIL_SIZE,
    result_to_text as _result_to_text,
    truncate_result as _truncate_result,
)
from .schema import TOOLS
from .actions import dispatch_channel_action
from .channel import (
    _notify_channel,
    _notify_done,
    _notify_error,
    _notify_reply,
    _notify_running,
    _remember_task_context,
    _set_active_session,
)
from .sse_bridge import _SSEBridge as _BaseSSEBridge
from .task_proxy import MCPGatewayProxy
from .tool_handlers import cancel_task_request, check_task_request, reply_task_request, run_task_request


def _resolve_git_cwd(cwd: str) -> str:
    return resolve_git_cwd(cwd, log_fn=_log)

# ── File logger ───────────────────────────────────────────────────────────────
from ..mcp_logging import _log, init_mcp_log as _init_log  # noqa: F401


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
_CODEX_APP_SERVER_HANDLE = None


def _init_gateway_client() -> None:
    global _GATEWAY_URL, _GATEWAY_API_KEY, _GATEWAY_CLIENT
    from ..config import load_settings
    _GATEWAY_URL, _GATEWAY_API_KEY, _GATEWAY_CLIENT = _init_gateway_client_impl(
        load_settings=load_settings,
        log_fn=_log,
    )


def _bootstrap_codex_app_server_writer_from_env():
    global _CODEX_APP_SERVER_HANDLE
    if _CODEX_APP_SERVER_HANDLE is not None:
        return _CODEX_APP_SERVER_HANDLE
    _CODEX_APP_SERVER_HANDLE = bootstrap_codex_app_server_from_env(
        env=os.environ,
        stream_lock=threading.Lock(),
        log_fn=_log,
    )
    return _CODEX_APP_SERVER_HANDLE


def _cleanup_codex_app_server_writer() -> None:
    global _CODEX_APP_SERVER_HANDLE
    handle = _CODEX_APP_SERVER_HANDLE
    _CODEX_APP_SERVER_HANDLE = None
    if handle is not None:
        handle.close()


def _gateway_headers() -> dict[str, str]:
    return _gateway_headers_impl(_GATEWAY_API_KEY)


def _gateway_health_check(force: bool = False) -> bool:
    global _consecutive_failures, _last_health_check
    healthy, _consecutive_failures, _last_health_check = _gateway_health_check_impl(
        gateway_url=_GATEWAY_URL,
        gateway_client=_GATEWAY_CLIENT,
        consecutive_failures=_consecutive_failures,
        last_health_check=_last_health_check,
        max_consecutive_failures=_MAX_CONSECUTIVE_FAILURES,
        force=force,
        log_fn=_log,
    )
    return healthy


class _SSEBridge(_BaseSSEBridge):
    """mcp_server-local wrapper preserving existing test patch points."""

    def __init__(self, task_id: str, client: httpx.Client):
        def _dispatch_action(task_id: str, action) -> None:
            dispatch_channel_action(
                task_id=task_id,
                action=action,
                notify_channel=_notify_channel,
                notify_done=_notify_done,
                notify_error=_notify_error,
                notify_running=_notify_running,
            )

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
        dispatch_channel_action(
            task_id=self.task_id,
            action=action,
            notify_channel=_notify_channel,
            notify_done=_notify_done,
            notify_error=_notify_error,
            notify_running=_notify_running,
        )


def _start_sse_bridge(task_id: str) -> _SSEBridge:
    """Start SSE bridge. Returns the bridge instance."""
    if not _GATEWAY_CLIENT:
        _init_gateway_client()
    if _GATEWAY_CLIENT is None:
        raise RuntimeError("Gateway client is not initialized")

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


def _build_mcp_app(host: str = "0.0.0.0", port: int = 3737):
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

    if _GATEWAY_URL is None or _GATEWAY_CLIENT is None:
        _init_gateway_client()
    if _GATEWAY_URL is None or _GATEWAY_CLIENT is None:
        raise RuntimeError("Gateway client is not initialized")

    proxy = MCPGatewayProxy(
        gateway_url=_GATEWAY_URL,
        gateway_client=_GATEWAY_CLIENT,
        gateway_headers=_gateway_headers,
        start_sse_bridge=_start_sse_bridge,
        cleanup_sse_bridge=_cleanup_sse_bridge,
        notify_error=_notify_error,
        notify_reply=_notify_reply,
        notify_channel=_notify_channel,
        truncate_result=_truncate_result,
        remember_task_context=_remember_task_context,
    )

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

        return run_task_request(
            task=task,
            cwd=cwd,
            model=model,
            max_turns=max_turns,
            proxy=proxy,
            result_to_text=_result_to_text,
            gateway_health_check=_gateway_health_check,
            resolve_git_cwd=_resolve_git_cwd,
            log_fn=_log,
        )

    @mcp_app.tool(description=TOOLS[1]["description"])
    async def reply_task(task_id: str, message: str) -> str:
        """Send a reply to HermitAgent."""
        _set_active_session(mcp_app.get_context().session, asyncio.get_running_loop())
        _log(f"[req] reply_task task_id={task_id} msg={message[:60]}")

        return reply_task_request(
            task_id=task_id,
            message=message,
            proxy=proxy,
            result_to_text=_result_to_text,
            log_fn=_log,
        )

    @mcp_app.tool(description=TOOLS[2]["description"])
    async def check_task(task_id: str, full: bool = False) -> str:
        """Check the current status of a background task."""
        _set_active_session(mcp_app.get_context().session, asyncio.get_running_loop())
        _log(f"[req] check_task task_id={task_id} full={full}")

        return check_task_request(
            task_id=task_id,
            full=full,
            proxy=proxy,
            result_to_text=_result_to_text,
            log_fn=_log,
        )

    @mcp_app.tool(description=TOOLS[3]["description"])
    async def cancel_task(task_id: str) -> str:
        """Cancel a running task."""
        _log(f"[req] cancel_task task_id={task_id}")

        return cancel_task_request(
            task_id=task_id,
            proxy=proxy,
            result_to_text=_result_to_text,
            log_fn=_log,
        )

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
    atexit.register(_cleanup_codex_app_server_writer)
    _bootstrap_codex_app_server_writer_from_env()

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
    atexit.register(_cleanup_codex_app_server_writer)
    _bootstrap_codex_app_server_writer_from_env()

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
