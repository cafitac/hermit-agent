"""Shared MCP logger — used by mcp_server.py and mcp_channel.py."""
from __future__ import annotations

import os
import time

from .log_retention import append_text_log

_LOG_PATH = os.path.expanduser("~/.hermit/mcp_server.log")


def init_mcp_log() -> None:
    os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)


def _log(line: str) -> None:
    ts = time.strftime("%H:%M:%S")
    try:
        append_text_log(_LOG_PATH, f"[{ts}] {line}\n")
    except Exception:
        pass
