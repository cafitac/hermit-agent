"""Installation and readiness checks for the Hermit MCP executor."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from .config import GLOBAL_SETTINGS_PATH, init_settings_file

VALID_INSTALL_TARGETS = ("all", "claude", "codex")
MCP_SERVER_NAME = "hermit"
_GATEWAY_URL = "http://127.0.0.1:8765"


@dataclass(frozen=True)
class MCPInstallSummary:
    target: str
    settings_path: str
    gateway_status: str
    claude_status: str = "skipped"
    codex_status: str = "skipped"

    @property
    def succeeded(self) -> bool:
        return self.gateway_status in {"healthy", "started"} and all(
            status in {"registered", "unchanged", "skipped"}
            for status in (self.claude_status, self.codex_status)
        )


def resolve_hermit_mcp_stdio_entry() -> dict[str, object]:
    return {"type": "stdio", "command": "hermit", "args": ["mcp-server"]}


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def ensure_gateway_api_key(*, settings_path: Path) -> None:
    payload = _read_json(settings_path)
    if payload.get("gateway_api_key"):
        return
    payload["gateway_api_key"] = f"hermit-mcp-{secrets.token_hex(16)}"
    _write_json(settings_path, payload)


def inspect_claude_mcp_registration(*, claude_command: str = "claude") -> str:
    """Check the user-scoped server through Claude Code's supported CLI."""
    try:
        current = subprocess.run(
            [claude_command, "mcp", "get", MCP_SERVER_NAME],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        return "missing-claude-cli"
    if current.returncode != 0:
        return "missing"
    output = f"{current.stdout}\n{current.stderr}"
    return "registered" if _codex_entry_is_current(output) else "outdated"


def register_claude_mcp(*, claude_command: str = "claude") -> str:
    status = inspect_claude_mcp_registration(claude_command=claude_command)
    if status == "registered":
        return "unchanged"
    if status == "missing-claude-cli":
        return status
    if status == "outdated":
        subprocess.run(
            [claude_command, "mcp", "remove", MCP_SERVER_NAME],
            capture_output=True,
            text=True,
            timeout=15,
        )
    try:
        created = subprocess.run(
            [claude_command, "mcp", "add", MCP_SERVER_NAME, "--scope", "user", "--", "hermit", "mcp-server"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        return "missing-claude-cli"
    if created.returncode != 0:
        message = created.stderr.strip() or created.stdout.strip() or "Claude Code MCP registration failed"
        return f"failed ({message})"
    return "registered"


def _codex_entry_is_current(stdout: str) -> bool:
    normalized = stdout.casefold()
    return "hermit" in normalized and "mcp-server" in normalized


def ensure_codex_mcp_registered(*, codex_command: str) -> str:
    try:
        current = subprocess.run(
            [codex_command, "mcp", "get", MCP_SERVER_NAME, "--json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        return "missing-codex-cli"
    if current.returncode == 0 and _codex_entry_is_current(current.stdout):
        return "unchanged"
    if current.returncode == 0:
        subprocess.run([codex_command, "mcp", "remove", MCP_SERVER_NAME], capture_output=True, text=True, timeout=15)
    try:
        created = subprocess.run(
            [codex_command, "mcp", "add", MCP_SERVER_NAME, "--", "hermit", "mcp-server"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        return "missing-codex-cli"
    if created.returncode != 0:
        message = created.stderr.strip() or created.stdout.strip() or "Codex MCP registration failed"
        return f"failed ({message})"
    return "registered"


def probe_gateway_health(*, timeout: float = 2.0) -> bool:
    try:
        with urlopen(f"{_GATEWAY_URL}/health", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False
    return payload.get("service") == "hermit_agent-gateway"


def ensure_gateway_running(*, wait_seconds: float = 8.0) -> str:
    if probe_gateway_health():
        return "healthy"
    bin_dir = Path(sys.executable).resolve().parent
    launcher = bin_dir / ("hermit-gateway.exe" if os.name == "nt" else "hermit-gateway")
    if not launcher.exists():
        found = shutil.which("hermit-gateway")
        if not found:
            return "missing-launcher"
        launcher = Path(found)
    subprocess.Popen(
        [str(launcher)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if probe_gateway_health():
            return "started"
        time.sleep(0.25)
    return "not-running"


def install_mcp_host(
    *, target: str, cwd: str, claude_command: str = "claude", codex_command: str = "codex"
) -> MCPInstallSummary:
    if target not in VALID_INSTALL_TARGETS:
        raise ValueError(f"Unknown install target: {target}")
    settings_path = init_settings_file()
    ensure_gateway_api_key(settings_path=settings_path)
    gateway_status = ensure_gateway_running()
    claude_status = register_claude_mcp(claude_command=claude_command) if target in {"all", "claude"} else "skipped"
    codex_status = ensure_codex_mcp_registered(codex_command=codex_command) if target in {"all", "codex"} else "skipped"
    return MCPInstallSummary(target, str(settings_path), gateway_status, claude_status, codex_status)


def inspect_mcp_install(
    *, cwd: str, claude_command: str = "claude", codex_command: str = "codex"
) -> MCPInstallSummary:
    try:
        codex = subprocess.run([codex_command, "mcp", "get", MCP_SERVER_NAME, "--json"], capture_output=True, text=True, timeout=10)
        codex_status = "registered" if codex.returncode == 0 and _codex_entry_is_current(codex.stdout) else "missing"
    except FileNotFoundError:
        codex_status = "missing-codex-cli"
    return MCPInstallSummary(
        "all",
        str(GLOBAL_SETTINGS_PATH),
        "healthy" if probe_gateway_health() else "not-running",
        inspect_claude_mcp_registration(claude_command=claude_command),
        codex_status,
    )


def format_install_summary(summary: MCPInstallSummary) -> str:
    title = "Hermit MCP installation complete." if summary.succeeded else "Hermit MCP installation needs attention."
    lines = [title, f"- Gateway: {summary.gateway_status}"]
    if summary.target in {"all", "claude"}:
        lines.append(f"- Claude Code MCP: {summary.claude_status}")
    if summary.target in {"all", "codex"}:
        lines.append(f"- Codex MCP: {summary.codex_status}")
    lines.append("Restart the selected host, then delegate a coding task to Hermit.")
    return "\n".join(lines)


def format_doctor_summary(summary: MCPInstallSummary) -> str:
    lines = ["Hermit MCP readiness", f"- Gateway: {summary.gateway_status}", f"- Claude Code MCP: {summary.claude_status}", f"- Codex MCP: {summary.codex_status}"]
    if not summary.succeeded or summary.gateway_status != "healthy":
        lines.append("Run `hermit install claude` or `hermit install codex` to repair the selected host.")
    return "\n".join(lines)
