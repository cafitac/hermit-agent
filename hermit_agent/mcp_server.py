"""StdIO MCP boundary for the Hermit executor.

The server intentionally exposes only task lifecycle operations.  Hosts poll
``check_task`` for progress or a waiting prompt; there is no host-specific
channel, UI bridge, or secondary interaction protocol.
"""

from __future__ import annotations

import atexit
import sys

from .config import load_settings
from .mcp_gateway import gateway_headers, gateway_health_check, init_gateway_client
from .mcp_paths import resolve_git_cwd
from .mcp_results import HEAD_SIZE, RESULT_CAP, TAIL_SIZE
from .mcp_results import result_to_text as _result_to_text
from .mcp_results import truncate_result as _truncate_result
from .mcp_schema import TOOLS
from .mcp_task_proxy import MCPGatewayProxy
from .mcp_tool_handlers import cancel_task_request, check_task_request, reply_task_request, run_task_request

_GATEWAY_URL: str | None = None
_GATEWAY_API_KEY: str | None = None
_GATEWAY_CLIENT = None
_consecutive_gateway_failures = 0
_last_gateway_health_check = 0.0
SERVER_INSTRUCTIONS = (
    "Delegate bounded implementation, debugging, test, and repository-maintenance work to Hermit. "
    "Keep product decisions, broad architecture, security-sensitive changes, and final review in the host agent. "
    "Use run_task(strategy='auto') only for complex refactors, migrations, or security-sensitive work; "
    "it adds read-only planning and review. Start with run_task, poll with check_task, and use reply_task "
    "only when Hermit asks for input or permission."
)


def _log(message: str) -> None:
    print(f"[hermit-mcp] {message}", file=sys.stderr, flush=True)


def _init_gateway_client() -> None:
    global _GATEWAY_URL, _GATEWAY_API_KEY, _GATEWAY_CLIENT
    _GATEWAY_URL, _GATEWAY_API_KEY, _GATEWAY_CLIENT = init_gateway_client(
        load_settings=load_settings,
        log_fn=_log,
    )


def _gateway_headers() -> dict[str, str]:
    return gateway_headers(_GATEWAY_API_KEY)


def _gateway_health_check(force: bool = False) -> bool:
    global _consecutive_gateway_failures, _last_gateway_health_check
    healthy, _consecutive_gateway_failures, _last_gateway_health_check = gateway_health_check(
        gateway_url=_GATEWAY_URL,
        gateway_client=_GATEWAY_CLIENT,
        consecutive_failures=_consecutive_gateway_failures,
        last_health_check=_last_gateway_health_check,
        max_consecutive_failures=3,
        force=force,
        log_fn=_log,
    )
    return healthy


def _resolve_git_cwd(cwd: str) -> str:
    return resolve_git_cwd(cwd, log_fn=_log)


def _noop(*_args, **_kwargs) -> None:
    return None


def _build_proxy() -> MCPGatewayProxy:
    if _GATEWAY_URL is None or _GATEWAY_CLIENT is None:
        _init_gateway_client()
    if _GATEWAY_URL is None or _GATEWAY_CLIENT is None:
        raise RuntimeError("Gateway client is not initialized")
    return MCPGatewayProxy(
        gateway_url=_GATEWAY_URL,
        gateway_client=_GATEWAY_CLIENT,
        gateway_headers=_gateway_headers,
        start_sse_bridge=_noop,
        cleanup_sse_bridge=_noop,
        notify_error=_noop,
        notify_reply=_noop,
        notify_channel=_noop,
        truncate_result=_truncate_result,
    )


def _build_mcp_app():
    from mcp.server.fastmcp import FastMCP

    mcp_app = FastMCP("hermit", instructions=SERVER_INSTRUCTIONS)
    proxy = _build_proxy()

    @mcp_app.tool(description=TOOLS[0]["description"])
    async def run_task(task: str, cwd: str, model: str = "", max_turns: int = 200, strategy: str = "single") -> str:
        return run_task_request(
            task=task,
            cwd=cwd,
            model=model,
            max_turns=max_turns,
            strategy=strategy,
            proxy=proxy,
            result_to_text=_result_to_text,
            gateway_health_check=_gateway_health_check,
            resolve_git_cwd=_resolve_git_cwd,
            log_fn=_log,
        )

    @mcp_app.tool(description=TOOLS[1]["description"])
    async def reply_task(task_id: str, message: str) -> str:
        return reply_task_request(task_id=task_id, message=message, proxy=proxy, result_to_text=_result_to_text, log_fn=_log)

    @mcp_app.tool(description=TOOLS[2]["description"])
    async def check_task(task_id: str, full: bool = False) -> str:
        return check_task_request(task_id=task_id, full=full, proxy=proxy, result_to_text=_result_to_text, log_fn=_log)

    @mcp_app.tool(description=TOOLS[3]["description"])
    async def cancel_task(task_id: str) -> str:
        return cancel_task_request(task_id=task_id, proxy=proxy, result_to_text=_result_to_text, log_fn=_log)

    return mcp_app


def main() -> None:
    _init_gateway_client()
    atexit.register(lambda: _GATEWAY_CLIENT.close() if _GATEWAY_CLIENT is not None else None)
    _build_mcp_app().run(transport="stdio")


if __name__ == "__main__":
    main()
