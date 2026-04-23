"""HermitAgent installation/configuration diagnostics (`/doctor` slash command backend).

Read-only diagnostics: HERMIT.md, ~/.hermit directory, hooks.json, skills, permissions floor.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .install_flow import run_install, run_startup_self_heal


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
    lines.append(f"- install flow: gateway={install.gateway_status}, mcp={install.mcp_registration_status}, codex={install.codex_install_status}")
    lines.append("- codex-facing surface remains: hermit-channel MCP")
    if install.codex_runtime_version:
        lines.append(f"- codex integration runtime version: {install.codex_runtime_version}")
    if install.next_steps:
        lines.extend(["", "Next:"])
        lines.extend([f"{i}. {step}" for i, step in enumerate(install.next_steps, 1)])
    return "\n".join(lines)
