"""Start the local gateway when needed, then run the stdio MCP server."""

from __future__ import annotations

import os
import sys

from .mcp_install import ensure_gateway_running, probe_gateway_health


def main() -> None:
    auto_start = os.environ.get("HERMIT_MCP_AUTO_GATEWAY", "1").strip().lower() not in {"0", "false", "no"}
    if auto_start and not probe_gateway_health():
        status = ensure_gateway_running()
        if status not in {"healthy", "started"}:
            print(f"[hermit-mcp-server] Gateway is unavailable: {status}.", file=sys.stderr)
    from .mcp_server import main as run_mcp_server

    run_mcp_server()


if __name__ == "__main__":
    main()
