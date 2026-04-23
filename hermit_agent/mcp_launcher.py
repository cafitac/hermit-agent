from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from .install_flow import probe_gateway_health


def _auto_gateway_enabled() -> bool:
    raw = str(os.environ.get("HERMIT_MCP_AUTO_GATEWAY", "1")).strip().lower()
    return raw not in {"0", "false", "no"}


def _gateway_wait_seconds() -> int:
    raw = str(os.environ.get("HERMIT_MCP_GATEWAY_WAIT_SEC", "8")).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 8


def _find_gateway_launcher() -> Path | None:
    scripts_dir = Path(sys.executable).resolve().parent
    candidates = (
        scripts_dir / "hermit-gateway",
        scripts_dir / "hermit-gateway.exe",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def ensure_gateway() -> None:
    if not _auto_gateway_enabled():
        return
    if probe_gateway_health():
        return
    launcher = _find_gateway_launcher()
    if launcher is None:
        print("[hermit-mcp-server] Gateway launcher not found; continuing without auto-start.", file=sys.stderr)
        return

    subprocess.Popen(
        [str(launcher)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.time() + _gateway_wait_seconds()
    while time.time() < deadline:
        if probe_gateway_health():
            return
        time.sleep(1)


def main() -> None:
    ensure_gateway()
    from .mcp_server import main as run_mcp_server

    run_mcp_server()


if __name__ == "__main__":
    main()
