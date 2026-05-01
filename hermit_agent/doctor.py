"""HermitAgent installation/configuration diagnostics (`/doctor` slash command backend).

Read-only diagnostics: HERMIT.md, ~/.hermit directory, hooks.json, skills, permissions floor.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .install_flow import resolve_hermit_mcp_stdio_entry, run_install, run_startup_self_heal


class DiagStatus(Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class DiagCheck:
    name: str
    status: DiagStatus
    message: str = ""


@dataclass
class DiagReport:
    checks: list[DiagCheck] = field(default_factory=list)

    @property
    def overall(self) -> DiagStatus:
        if any(c.status == DiagStatus.FAIL for c in self.checks):
            return DiagStatus.FAIL
        if any(c.status == DiagStatus.WARN for c in self.checks):
            return DiagStatus.WARN
        return DiagStatus.PASS

    def format(self) -> str:
        icon = {DiagStatus.PASS: "✅", DiagStatus.WARN: "⚠️ ", DiagStatus.FAIL: "❌"}
        lines = [f"HermitAgent Doctor — overall: {icon[self.overall]} {self.overall.value}", ""]
        for c in self.checks:
            lines.append(f"{icon[c.status]} {c.name}: {c.message}")
        return "\n".join(lines)


def _check_hermit_agent_md(cwd: str, home: str) -> DiagCheck:
    project_path = Path(cwd) / "HERMIT.md"
    global_path = Path(home) / ".hermit" / "HERMIT.md"
    if project_path.exists():
        return DiagCheck("HERMIT.md", DiagStatus.PASS, f"found at {project_path}")
    if global_path.exists():
        return DiagCheck("HERMIT.md", DiagStatus.PASS, f"found at {global_path} (global)")
    return DiagCheck(
        "HERMIT.md",
        DiagStatus.WARN,
        "no HERMIT.md found in project or ~/.hermit/ — run /init to create one",
    )


def _check_hermit_agent_dir(home: str) -> DiagCheck:
    path = Path(home) / ".hermit"
    if path.is_dir():
        return DiagCheck("~/.hermit dir", DiagStatus.PASS, f"{path}")
    return DiagCheck(
        "~/.hermit dir",
        DiagStatus.WARN,
        f"{path} does not exist — will be created on first run",
    )


def _check_hooks_json(home: str) -> DiagCheck:
    path = Path(home) / ".hermit" / "hooks.json"
    if not path.exists():
        return DiagCheck("hooks.json", DiagStatus.PASS, "absent (OK — no hooks configured)")
    try:
        json.loads(path.read_text())
        return DiagCheck("hooks.json", DiagStatus.PASS, f"valid JSON at {path}")
    except json.JSONDecodeError as exc:
        return DiagCheck("hooks.json", DiagStatus.FAIL, f"invalid JSON: {exc}")


def _check_skills(home: str) -> DiagCheck:
    sources = [
        (Path(home) / ".hermit" / "skills", "hermit_agent"),
        (Path(home) / ".claude" / "skills", "claude"),
    ]
    counts = {}
    for path, label in sources:
        if path.is_dir():
            counts[label] = sum(1 for _ in path.glob("*/SKILL.md"))
    if not counts:
        return DiagCheck("skills", DiagStatus.WARN, "no skills directory found")
    summary = ", ".join(f"{label}={n}" for label, n in counts.items())
    total = sum(counts.values())
    status = DiagStatus.PASS if total > 0 else DiagStatus.WARN
    return DiagCheck("skills", status, summary)


def _check_sensitive_deny() -> DiagCheck:
    """Verify the operation of the sensitive file deny floor added in Priority 1."""
    try:
        from .permissions import PermissionBehavior, PermissionChecker, PermissionMode

        checker = PermissionChecker(mode=PermissionMode.YOLO)
        result = checker.check_3step(
            "read_file", {"path": "/tmp/__doctor_probe__/.env"}, is_read_only=True
        )
        if result.behavior == PermissionBehavior.DENY:
            return DiagCheck(
                "permissions.sensitive_deny",
                DiagStatus.PASS,
                "sensitive file floor active (including YOLO)"
            )
        return DiagCheck(
            "permissions.sensitive_deny",
            DiagStatus.FAIL,
            "sensitive file floor inactive — Priority 1 regression possible"
        )
    except Exception as exc:
        return DiagCheck("permissions.sensitive_deny", DiagStatus.FAIL, f"probe failed: {exc}")


def _check_local_backend(cwd: str) -> DiagCheck:
    """Check local LLM backend configuration and health."""
    from .config import load_settings
    from .local_runtime import (
        detect_all_runtimes,
        detect_local_runtime,
        get_install_hints,
        BACKEND_MLX,
        BACKEND_LLAMA_CPP,
        BACKEND_OLLAMA,
    )

    cfg = load_settings(cwd=cwd)
    configured = cfg.get("local_backend")

    # If a backend is configured, verify it's still healthy
    if configured:
        detected = detect_local_runtime()
        all_runtimes = detect_all_runtimes()
        configured_runtime = next(
            (r for r in all_runtimes if r.backend == configured), None
        )

        if configured_runtime and configured_runtime.available:
            details = f"{configured} (auto-detected) — server responding on {configured_runtime.base_url}"
            # Check for alternatives
            alternatives = [r for r in all_runtimes if r.available and r.backend != configured]
            if alternatives:
                alt_str = ", ".join(f"{r.backend} ({r.base_url})" for r in alternatives)
                details += f" | Alternatives: {alt_str}"
            # Platform recommendation
            import sys as _sys
            import platform as _platform
            if _sys.platform == "darwin" and _platform.machine() == "arm64":
                if configured == BACKEND_MLX:
                    details += " | Optimal for Apple Silicon"
                elif configured == BACKEND_OLLAMA and any(r.backend == BACKEND_MLX and r.available for r in all_runtimes):
                    details += " | Tip: MLX is optimal for Apple Silicon"
            return DiagCheck("local_backend", DiagStatus.PASS, details)
        else:
            hint = get_install_hints(configured) or ""
            return DiagCheck(
                "local_backend",
                DiagStatus.WARN,
                f"configured as '{configured}' but backend not responding | hint: {hint}",
            )

    # No backend configured — check if one is available
    detected = detect_local_runtime()
    if detected.available:
        return DiagCheck(
            "local_backend",
            DiagStatus.WARN,
            f"{detected.backend} detected ({detected.base_url}) but not configured — run 'hermit_agent config local-backend --re-detect'",
        )

    return DiagCheck(
        "local_backend",
        DiagStatus.WARN,
        "no local LLM backend detected — install Ollama (https://ollama.com) or run 'hermit_agent config local-backend --list'",
    )


def _check_agent_learner(home: str) -> DiagCheck:
    try:
        import agent_learner  # noqa: F401
        installed = True
    except ImportError:
        installed = False

    if not installed:
        return DiagCheck(
            "agent-learner",
            DiagStatus.WARN,
            "not installed — run `hermit install` to install automatically",
        )

    claude_settings = Path(home) / ".claude" / "settings.json"
    codex_hooks = Path(home) / ".codex" / "hooks.json"
    missing: list[str] = []
    for label, path in (("claude", claude_settings), ("codex", codex_hooks)):
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            hooks = data.get("hooks", {}).get("Stop", [])
            if not any("agent-learner" in str(h) for h in hooks):
                missing.append(label)
        except Exception:
            missing.append(label)

    if missing:
        return DiagCheck(
            "agent-learner",
            DiagStatus.WARN,
            f"installed but Stop hook missing for: {', '.join(missing)} — run `hermit install` to repair",
        )
    return DiagCheck("agent-learner", DiagStatus.PASS, "installed, Stop hooks registered (claude + codex)")


def _extract_mcp_servers(payload: object) -> dict[str, object]:
    if isinstance(payload, dict):
        for key in ("servers", "mcpServers", "mcp_servers"):
            value = payload.get(key)
            if isinstance(value, dict):
                return value
            if isinstance(value, list):
                servers: dict[str, object] = {}
                for item in value:
                    if isinstance(item, dict) and item.get("name"):
                        servers[str(item["name"])] = item
                return servers
        if "hermit-channel" in payload:
            return payload
    if isinstance(payload, list):
        servers = {}
        for item in payload:
            if isinstance(item, dict) and item.get("name"):
                servers[str(item["name"])] = item
        return servers
    return {}


def _server_transport(server: object) -> dict[str, object]:
    if not isinstance(server, dict):
        return {}
    transport = server.get("transport")
    if isinstance(transport, dict):
        return transport
    return server


def _check_hermes_mcp(cwd: str) -> DiagCheck:
    if shutil.which("hermes") is None:
        return DiagCheck(
            "Hermes MCP",
            DiagStatus.WARN,
            "hermes command not found — run `hermit install --print-hermes-mcp-config` after installing Hermes Agent",
        )

    try:
        proc = subprocess.run(
            ["hermes", "mcp", "list", "--json"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DiagCheck("Hermes MCP", DiagStatus.WARN, f"unable to inspect Hermes MCP servers: {exc}")
    raw_output = ""
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "hermes mcp list failed"
        if "--json" not in message and "unrecognized arguments" not in message:
            return DiagCheck("Hermes MCP", DiagStatus.WARN, f"unable to inspect Hermes MCP servers: {message}")
        try:
            proc = subprocess.run(
                ["hermes", "mcp", "list"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return DiagCheck("Hermes MCP", DiagStatus.WARN, f"unable to inspect Hermes MCP servers: {exc}")
        if proc.returncode != 0:
            message = proc.stderr.strip() or proc.stdout.strip() or "hermes mcp list failed"
            return DiagCheck("Hermes MCP", DiagStatus.WARN, f"unable to inspect Hermes MCP servers: {message}")
        raw_output = proc.stdout or ""
    else:
        raw_output = proc.stdout or ""

    if raw_output and not raw_output.lstrip().startswith(("{", "[")):
        lowered = raw_output.lower()
        if "hermit-channel" in lowered and "hermit" in lowered and "mcp-server" in lowered:
            return DiagCheck("Hermes MCP", DiagStatus.PASS, "hermit-channel registered for Hermes Agent")
        if "hermit-channel" not in lowered or "no mcp servers" in lowered:
            return DiagCheck(
                "Hermes MCP",
                DiagStatus.WARN,
                "hermit-channel missing — run `hermit install --print-hermes-mcp-config` and register the printed snippet",
            )
        return DiagCheck("Hermes MCP", DiagStatus.WARN, "hermit-channel present but Hermes text output did not expose the expected hermit mcp-server transport")

    try:
        payload = json.loads(raw_output or "{}")
    except json.JSONDecodeError as exc:
        return DiagCheck("Hermes MCP", DiagStatus.WARN, f"Hermes MCP list returned invalid JSON: {exc}")

    servers = _extract_mcp_servers(payload)
    server = servers.get("hermit-channel")
    if server is None:
        return DiagCheck(
            "Hermes MCP",
            DiagStatus.WARN,
            "hermit-channel missing — run `hermit install --print-hermes-mcp-config` and register the printed snippet",
        )

    expected = resolve_hermit_mcp_stdio_entry(cwd=cwd)
    transport = _server_transport(server)
    command = str(transport.get("command") or "")
    args = [str(arg) for arg in (transport.get("args") or [])] if isinstance(transport.get("args"), list) else []
    expected_args = [str(arg) for arg in (expected.get("args") or [])] if isinstance(expected.get("args"), list) else []
    if command == str(expected["command"]) and args == expected_args:
        return DiagCheck("Hermes MCP", DiagStatus.PASS, "hermit-channel registered for Hermes Agent")
    return DiagCheck(
        "Hermes MCP",
        DiagStatus.WARN,
        f"hermit-channel registered but points to command={command!r} args={args!r}; expected hermit mcp-server",
    )


def run_diagnostics(cwd: str | None = None, home: str | None = None) -> DiagReport:
    """Diagnose HermitAgent configuration. Testable by injecting cwd/home."""
    cwd = cwd or os.getcwd()
    home = home or os.path.expanduser("~")
    checks = [
        _check_hermit_agent_md(cwd, home),
        _check_hermit_agent_dir(home),
        _check_hooks_json(home),
        _check_skills(home),
        _check_sensitive_deny(),
        _check_local_backend(cwd),
        _check_agent_learner(home),
        _check_hermes_mcp(cwd),
    ]
    return DiagReport(checks=checks)


def format_doctor_fix_summary(*, cwd: str) -> str:
    startup = run_startup_self_heal(cwd=cwd)
    install = run_install(
        cwd=cwd,
        assume_yes=True,
        skip_mcp_register=False,
        skip_codex=False,
    )

    lines = ["Hermit doctor --fix complete.", "", "Repairs:"]
    lines.append(f"- startup heal: gateway={startup.gateway_status}, mcp={startup.mcp_registration_status}, codex={startup.codex_runtime_status}")
    lines.append(f"- install flow: gateway={install.gateway_status}, mcp={install.mcp_registration_status}, codex={install.codex_install_status}, agent-learner={install.agent_learner_status}")
    lines.append("- codex-facing surface remains: hermit-channel MCP")
    if install.codex_runtime_version:
        lines.append(f"- codex integration runtime version: {install.codex_runtime_version}")
    if install.next_steps:
        lines.extend(["", "Next:"])
        lines.extend([f"{i}. {step}" for i, step in enumerate(install.next_steps, 1)])
    return "\n".join(lines)
