"""Installation and readiness checks for the Hermit MCP executor."""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from urllib.parse import urlparse

from .config import GLOBAL_SETTINGS_PATH, init_settings_file, load_settings
from .executor_readiness import ExecutorReadiness, inspect_executor_readiness

VALID_INSTALL_TARGETS = ("all", "claude", "codex")
MCP_SERVER_NAME = "hermit"
_DEFAULT_GATEWAY_URL = "http://127.0.0.1:8765"
_URL_CREDENTIALS = re.compile(r"(?i)((?:https?|wss?)://)[^/@\s]+@")
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[^\s,;\)\]\}]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|gateway[_-]?api[_-]?key|token|secret|password|passwd)\b\s*([:=])\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_SECRET_QUERY = re.compile(r"(?i)([?&](?:api[_-]?key|token|secret|password|passwd)=[^&#\s]*)")
_KNOWN_SECRET = re.compile(r"\b(?:sk|rk|pk|ghp|gho|pypi)-[A-Za-z0-9_-]{8,}\b|\bhermit-mcp-[a-f0-9]{16,}\b", re.IGNORECASE)


@dataclass(frozen=True)
class MCPInstallSummary:
    target: str
    settings_path: str
    gateway_status: str
    claude_status: str = "skipped"
    codex_status: str = "skipped"
    executor: ExecutorReadiness | None = None

    @property
    def succeeded(self) -> bool:
        return self.gateway_status in {"healthy", "started"} and (self.executor is None or self.executor.ready) and all(
            status in {"registered", "unchanged", "skipped"}
            for status in (self.claude_status, self.codex_status)
        )


def resolve_hermit_mcp_stdio_entry() -> dict[str, object]:
    return {"type": "stdio", "command": "hermit", "args": ["mcp-server"]}


def redact_diagnostic_text(value: str) -> str:
    """Remove credentials from diagnostics that users may paste into an issue."""
    redacted = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", value)
    redacted = _BEARER_TOKEN.sub("Bearer [REDACTED]", redacted)
    redacted = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", redacted)
    redacted = _SECRET_QUERY.sub(lambda match: match.group(1).split("=", 1)[0] + "=[REDACTED]", redacted)
    return _KNOWN_SECRET.sub("[REDACTED]", redacted)


def doctor_report(summary: MCPInstallSummary) -> dict[str, object]:
    """Return the stable, paste-safe report used by ``hermit doctor --json``."""
    executor = summary.executor
    return {
        "schema_version": 1,
        "ready": summary.succeeded and summary.gateway_status == "healthy",
        "hosts": {
            "claude_code": redact_diagnostic_text(summary.claude_status),
            "codex": redact_diagnostic_text(summary.codex_status),
        },
        "gateway": {"status": redact_diagnostic_text(summary.gateway_status)},
        "executor": {
            "status": redact_diagnostic_text(executor.status if executor else "unknown"),
            "details": [redact_diagnostic_text(detail) for detail in (executor.routes if executor else ())],
            "guidance": [redact_diagnostic_text(hint) for hint in (executor.guidance if executor else ())],
        },
    }


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


def probe_gateway_health(*, gateway_url: str = _DEFAULT_GATEWAY_URL, timeout: float = 2.0) -> bool:
    try:
        with urlopen(f"{gateway_url.rstrip('/')}/health", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False
    return payload.get("service") == "hermit_agent-gateway"


def _is_local_gateway_url(gateway_url: str) -> bool:
    parsed = urlparse(gateway_url)
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _is_port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _find_available_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _persist_gateway_url(settings_path: Path, gateway_url: str) -> None:
    payload = _read_json(settings_path)
    payload["gateway_url"] = gateway_url
    _write_json(settings_path, payload)


def ensure_gateway_running(*, settings_path: Path | None = None, gateway_url: str | None = None, wait_seconds: float = 8.0) -> str:
    settings_path = settings_path or GLOBAL_SETTINGS_PATH
    gateway_url = gateway_url or str(load_settings().get("gateway_url", _DEFAULT_GATEWAY_URL))
    if probe_gateway_health(gateway_url=gateway_url):
        return "healthy"
    if not _is_local_gateway_url(gateway_url):
        return "unreachable-external"

    parsed = urlparse(gateway_url)
    port = parsed.port or 8765
    host = "127.0.0.1"
    if not _is_port_available(host, port):
        # Another process owns the port. Do not stop or modify it; persist a
        # new loopback port before launching Hermit so future MCP processes use it.
        port = _find_available_port(host)
        gateway_url = f"http://{host}:{port}"
        _persist_gateway_url(settings_path, gateway_url)

    bin_dir = Path(sys.executable).resolve().parent
    launcher = bin_dir / ("hermit-gateway.exe" if os.name == "nt" else "hermit-gateway")
    if not launcher.exists():
        found = shutil.which("hermit-gateway")
        if not found:
            return "missing-launcher"
        launcher = Path(found)
    environment = os.environ.copy()
    environment.update({"HERMIT_GATEWAY_HOST": host, "HERMIT_GATEWAY_PORT": str(port)})
    subprocess.Popen(
        [str(launcher)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=environment,
    )
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if probe_gateway_health(gateway_url=gateway_url):
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
    gateway_status = ensure_gateway_running(settings_path=settings_path)
    claude_status = register_claude_mcp(claude_command=claude_command) if target in {"all", "claude"} else "skipped"
    codex_status = ensure_codex_mcp_registered(codex_command=codex_command) if target in {"all", "codex"} else "skipped"
    executor = inspect_executor_readiness(load_settings(cwd=cwd))
    return MCPInstallSummary(target, str(settings_path), gateway_status, claude_status, codex_status, executor)


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
        "healthy" if probe_gateway_health(gateway_url=str(load_settings(cwd=cwd).get("gateway_url", _DEFAULT_GATEWAY_URL))) else "not-running",
        inspect_claude_mcp_registration(claude_command=claude_command),
        codex_status,
        inspect_executor_readiness(load_settings(cwd=cwd)),
    )


def format_install_summary(summary: MCPInstallSummary) -> str:
    title = "Hermit MCP installation complete." if summary.succeeded else "Hermit MCP installation needs attention."
    lines = [title, f"- Gateway: {redact_diagnostic_text(summary.gateway_status)}"]
    if summary.target in {"all", "claude"}:
        lines.append(f"- Claude Code MCP: {redact_diagnostic_text(summary.claude_status)}")
    if summary.target in {"all", "codex"}:
        lines.append(f"- Codex MCP: {redact_diagnostic_text(summary.codex_status)}")
    if summary.executor:
        lines.append(f"- Executor: {redact_diagnostic_text(summary.executor.status)}")
        lines.extend(f"  - {redact_diagnostic_text(detail)}" for detail in summary.executor.routes)
        lines.extend(f"  - Next: {redact_diagnostic_text(hint)}" for hint in summary.executor.guidance)
    if summary.succeeded:
        lines.append("Restart the selected host, then delegate a coding task to Hermit.")
    else:
        lines.append("MCP registration may be complete, but Hermit will not accept work until the items above are ready.")
    return "\n".join(lines)


def format_doctor_summary(summary: MCPInstallSummary) -> str:
    report = doctor_report(summary)
    hosts = report["hosts"]
    gateway = report["gateway"]
    executor = report["executor"]
    lines = [
        "Hermit MCP readiness",
        f"- Gateway: {gateway['status']}",
        f"- Claude Code MCP: {hosts['claude_code']}",
        f"- Codex MCP: {hosts['codex']}",
        f"- Executor: {executor['status']}",
    ]
    lines.extend(f"  - {detail}" for detail in executor["details"])
    lines.extend(f"  - Next: {hint}" for hint in executor["guidance"])
    if not summary.succeeded or summary.gateway_status != "healthy":
        lines.append("Run `hermit install claude` or `hermit install codex` to repair the selected host.")
    return "\n".join(lines)
