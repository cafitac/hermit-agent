from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from .config import GLOBAL_SETTINGS_PATH, init_settings_file, load_settings


PLACEHOLDER_GATEWAY_KEY = "CHANGE_ME_AFTER_FIRST_RUN"


@dataclass
class InstallSummary:
    settings_path: str
    gateway_api_key_created: bool = False
    gateway_api_key_present: bool = False
    gateway_status: str = "unchecked"
    mcp_registration_status: str = "skipped"
    mcp_registration_path: str | None = None
    mcp_backup_path: str | None = None
    codex_install_status: str = "skipped"
    codex_runtime_version: str | None = None
    codex_marketplace_status: str = "skipped"
    codex_reply_hook_status: str = "skipped"
    codex_details: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


@dataclass
class StartupHealSummary:
    settings_initialized: bool = False
    gateway_api_key_created: bool = False
    gateway_status: str = "unchecked"
    mcp_registration_status: str = "unchecked"
    codex_runtime_status: str = "unchecked"

    @property
    def changed(self) -> bool:
        return self.settings_initialized or self.gateway_api_key_created or self.gateway_status == "started"


def _stdin_interactive() -> bool:
    try:
        return os.isatty(0)
    except Exception:
        return False


def _prompt_yes_no(question: str, *, default: bool = True, assume_yes: bool = False) -> bool:
    if assume_yes:
        return True
    if not _stdin_interactive():
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{question} {suffix} ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _backup_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}")


def _generate_gateway_api_key() -> str:
    return f"hermit-mcp-{secrets.token_hex(16)}"


def ensure_gateway_api_key(*, settings_path: Path) -> tuple[bool, str]:
    payload = _load_json(settings_path)
    api_key = str(payload.get("gateway_api_key") or "").strip()
    created = False
    if not api_key or api_key == PLACEHOLDER_GATEWAY_KEY:
        api_key = _generate_gateway_api_key()
        payload["gateway_api_key"] = api_key
        _write_json(settings_path, payload)
        created = True

    from .gateway.db import create_api_key, init_db, lookup_api_key

    async def _sync() -> None:
        await init_db()
        existing = await lookup_api_key(api_key)
        if existing is None:
            await create_api_key(api_key, "local")

    asyncio.run(_sync())
    return created, api_key


def resolve_hermit_mcp_stdio_entry(*, cwd: str) -> dict[str, object]:
    home = Path.home()
    candidates = (
        home / ".hermit" / "npm-runtime" / "venv" / "bin" / "hermit-mcp-server",
        home / ".hermit" / "npm-runtime" / "venv" / "Scripts" / "hermit-mcp-server.exe",
        Path(cwd) / ".venv" / "bin" / "hermit-mcp-server",
        Path(cwd) / ".venv" / "Scripts" / "hermit-mcp-server.exe",
    )
    for candidate in candidates:
        if candidate.exists():
            return {"type": "stdio", "command": str(candidate)}
    return {"type": "stdio", "command": str(Path(cwd) / "bin" / "mcp-server.sh")}


def inspect_claude_mcp_registration(*, command_path: Path | None = None, claude_json_path: Path | None = None, entry: dict[str, object] | None = None) -> str:
    target = claude_json_path or (Path.home() / ".claude.json")
    if not target.exists():
        return "missing"
    payload = _load_json(target)
    if not isinstance(payload, dict):
        return "invalid"
    entry = (((payload.get("mcpServers") or {}) if isinstance(payload.get("mcpServers"), dict) else {}).get("hermit-channel"))
    expected = entry if entry is not None else {"type": "stdio", "command": str(command_path)}
    return "registered" if entry == expected else "missing"


def register_claude_mcp(*, command_path: Path | None = None, claude_json_path: Path | None = None, entry: dict[str, object] | None = None) -> tuple[str, Path, Path | None]:
    target = claude_json_path or (Path.home() / ".claude.json")
    resolved_entry = entry if entry is not None else {"type": "stdio", "command": str(command_path)}
    name = "hermit-channel"

    payload = _load_json(target)
    backup_path: Path | None = None
    if target.exists():
        backup_path = _backup_path(target)
        shutil.copyfile(target, backup_path)

    if target.exists() and not payload:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    projects = payload.get("projects")
    if isinstance(projects, dict):
        for _, project in projects.items():
            if not isinstance(project, dict):
                continue
            mcp_servers = project.get("mcpServers")
            if not isinstance(mcp_servers, dict):
                continue
            for legacy_name in ("hermit-channel", "hermit"):
                mcp_servers.pop(legacy_name, None)
            if not mcp_servers:
                project.pop("mcpServers", None)

    mcp_servers = payload.setdefault("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        raise RuntimeError(f"{target} mcpServers is not an object")

    legacy = mcp_servers.get("hermit")
    if isinstance(legacy, dict) and legacy.get("type") in {"http", "sse"}:
        mcp_servers.pop("hermit", None)

    if mcp_servers.get(name) == resolved_entry:
        return "unchanged", target, backup_path

    mcp_servers[name] = resolved_entry
    _write_json(target, payload)
    return "registered", target, backup_path


def get_codex_runtime_version(*, cwd: str) -> str | None:
    from .codex_channels_adapter import load_codex_channels_settings

    settings = load_codex_channels_settings(load_settings(cwd=cwd), cwd)
    package_json = Path(settings.runtime_dir) / "node_modules" / "@cafitac" / "codex-channels" / "package.json"
    if not package_json.exists():
        return None
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except Exception:
        return None
    version = payload.get("version")
    return str(version) if version else None


def _desired_codex_runtime_version(*, cwd: str) -> str:
    from .codex_channels_adapter import _package_version, load_codex_channels_settings

    settings = load_codex_channels_settings(load_settings(cwd=cwd), cwd)
    return _package_version(settings.package_spec)


def ensure_codex_channels_ready(*, cwd: str, codex_command: str, scope: str) -> tuple[str, list[str], str | None]:
    from .codex_channels_adapter import install_codex_channels

    installed_version = get_codex_runtime_version(cwd=cwd)
    desired_version = _desired_codex_runtime_version(cwd=cwd)
    if installed_version == desired_version:
        return "healthy", [f"runtime version: {installed_version}"], installed_version

    report = install_codex_channels(cwd=cwd, codex_command=codex_command, scope=scope)
    details = [
        f"install mode: {report.install_mode}",
        f"runtime dir: {report.runtime_dir}",
        f"settings updated: {report.settings_path}",
        f"plugin bootstrap: {report.marketplace_path}",
    ]
    current_version = get_codex_runtime_version(cwd=cwd) or desired_version
    if installed_version and installed_version != desired_version:
        details.insert(0, f"runtime upgraded: {installed_version} -> {current_version}")
    return "installed", details, current_version


def ensure_codex_marketplace_registered(*, cwd: str, codex_command: str, scope: str) -> str:
    source_root = cwd if scope == "workspace" else str(Path.home())
    proc = subprocess.run(
        [codex_command, "plugin", "marketplace", "add", source_root],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "failed to register Codex marketplace"
        raise RuntimeError(message)

    output = proc.stdout.strip().lower()
    if "already added" in output:
        return "unchanged"
    if "added marketplace" in output:
        return "registered"
    return "registered"


def ensure_codex_mcp_registered(*, cwd: str, codex_command: str) -> str:
    desired_entry = resolve_hermit_mcp_stdio_entry(cwd=cwd)
    desired_command = str(desired_entry["command"])
    desired_args = [str(arg) for arg in desired_entry.get("args", []) or []]

    current = subprocess.run(
        [codex_command, "mcp", "get", "hermit-channel", "--json"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if current.returncode == 0:
        try:
            payload = json.loads(current.stdout)
        except Exception:
            payload = {}
        transport = payload.get("transport") if isinstance(payload, dict) else {}
        current_command = str((transport or {}).get("command") or "")
        current_args = [str(arg) for arg in ((transport or {}).get("args") or [])]
        if current_command == desired_command and current_args == desired_args:
            return "unchanged"
        subprocess.run(
            [codex_command, "mcp", "remove", "hermit-channel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    proc = subprocess.run(
        [codex_command, "mcp", "add", "hermit-channel", "--", desired_command, *desired_args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "failed to register Codex MCP"
        raise RuntimeError(message)
    return "registered"


def remove_codex_reply_hook(*, cwd: str, hooks_json_path: Path | None = None) -> str:
    target = hooks_json_path or (Path.home() / ".codex" / "hooks.json")
    payload = _load_json(target)
    if not isinstance(payload, dict):
        return "absent"
    hooks = payload.get("hooks")
    if not isinstance(hooks, dict):
        return "absent"
    entries = hooks.get("UserPromptSubmit")
    if not isinstance(entries, list):
        return "absent"

    command = str(Path(cwd).resolve() / "bin" / "codex-reply-hook.sh")
    normalized_command_suffix = "bin/codex-reply-hook.sh"
    retained_entries: list[Any] = []
    removed = False
    for entry in entries:
        if not isinstance(entry, dict):
            retained_entries.append(entry)
            continue
        hook_defs = entry.get("hooks")
        if not isinstance(hook_defs, list):
            retained_entries.append(entry)
            continue
        retained_hooks: list[Any] = []
        for hook in hook_defs:
            if not isinstance(hook, dict):
                retained_hooks.append(hook)
                continue
            hook_command = str(hook.get("command") or "")
            if hook_command == command or hook_command.endswith(normalized_command_suffix):
                removed = True
                continue
            retained_hooks.append(hook)
        if retained_hooks:
            next_entry = dict(entry)
            next_entry["hooks"] = retained_hooks
            retained_entries.append(next_entry)

    if not removed:
        return "absent"

    hooks["UserPromptSubmit"] = retained_entries
    _write_json(target, payload)
    return "removed"


def _gateway_health_url() -> str:
    cfg = load_settings()
    return str(cfg.get("gateway_url") or "http://localhost:8765").rstrip("/") + "/health"


def probe_gateway_health(*, timeout: float = 2.0) -> bool:
    try:
        with urlopen(_gateway_health_url(), timeout=timeout) as response:
            return 200 <= getattr(response, "status", 200) < 300
    except (URLError, OSError, ValueError):
        return False


def ensure_gateway_running(*, cwd: str) -> str:
    if probe_gateway_health():
        return "healthy"

    gateway_script = Path(cwd) / "bin" / "gateway.sh"
    if not gateway_script.exists():
        return "missing-script"

    proc = subprocess.run(
        [str(gateway_script), "--daemon"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return "start-failed"
    return "started" if probe_gateway_health(timeout=5.0) else "unhealthy"


def format_install_summary(summary: InstallSummary) -> str:
    lines = [
        "Hermit install is ready.",
        "",
        "Verified:",
        f"- settings file: {summary.settings_path}",
        f"- gateway API key: {'created' if summary.gateway_api_key_created else ('present' if summary.gateway_api_key_present else 'skipped')}",
        f"- gateway: {summary.gateway_status}",
        f"- MCP registration: {summary.mcp_registration_status}",
    ]
    if summary.mcp_registration_path:
        lines.append(f"- MCP config path: {summary.mcp_registration_path}")
    if summary.mcp_backup_path:
        lines.append(f"- MCP config backup: {summary.mcp_backup_path}")
    lines.append(f"- Codex integration: {summary.codex_install_status}")
    if summary.codex_runtime_version:
        lines.append(f"- Codex integration runtime version: {summary.codex_runtime_version}")
    lines.append(f"- Codex marketplace registration: {summary.codex_marketplace_status}")
    lines.append(f"- Legacy Codex reply hook: {summary.codex_reply_hook_status}")
    for detail in summary.codex_details:
        lines.append(f"  - {detail}")
    if summary.next_steps:
        lines.extend(["", "Next:"])
        lines.extend([f"{i}. {step}" for i, step in enumerate(summary.next_steps, 1)])
    return "\n".join(lines)


def run_install(
    *,
    cwd: str,
    codex_command: str = "codex",
    codex_scope: str = "user",
    assume_yes: bool = False,
    skip_mcp_register: bool = False,
    skip_codex: bool = False,
) -> InstallSummary:
    settings_path = init_settings_file(global_=True)
    summary = InstallSummary(settings_path=str(settings_path))

    create_key = _prompt_yes_no(
        "Create or repair the local gateway API key automatically?",
        default=True,
        assume_yes=assume_yes,
    )
    if create_key:
        created, _api_key = ensure_gateway_api_key(settings_path=settings_path)
        summary.gateway_api_key_created = created
        summary.gateway_api_key_present = True
    else:
        cfg = load_settings(cwd=cwd)
        summary.gateway_api_key_present = bool(cfg.get("gateway_api_key"))

    summary.gateway_status = ensure_gateway_running(cwd=cwd)
    if summary.gateway_status in {"missing-script", "start-failed", "unhealthy"}:
        summary.next_steps.append("Check the local gateway setup or run ./bin/gateway.sh --daemon manually.")

    if skip_mcp_register:
        summary.mcp_registration_status = "skipped"
    else:
        register_mcp = _prompt_yes_no(
            "Register Hermit MCP in ~/.claude.json automatically?",
            default=True,
            assume_yes=assume_yes,
        )
        if register_mcp:
            try:
                status, path, backup = register_claude_mcp(entry=resolve_hermit_mcp_stdio_entry(cwd=cwd))
                summary.mcp_registration_status = status
                summary.mcp_registration_path = str(path)
                summary.mcp_backup_path = str(backup) if backup else None
                summary.next_steps.append("Start Claude Code with --dangerously-load-development-channels server:hermit-channel.")
            except Exception as exc:
                summary.mcp_registration_status = f"failed ({exc})"
                summary.next_steps.append("Repair ~/.claude.json MCP registration before using Claude Code integration.")
        else:
            summary.mcp_registration_status = "skipped"

    if skip_codex:
        summary.codex_install_status = "skipped"
    else:
        install_codex = _prompt_yes_no(
            "Install or refresh Hermit's Codex integration automatically?",
            default=True,
            assume_yes=assume_yes,
        )
        if install_codex:
            try:
                status, details, version = ensure_codex_channels_ready(cwd=cwd, codex_command=codex_command, scope=codex_scope)
                summary.codex_install_status = status
                summary.codex_runtime_version = version
                summary.codex_marketplace_status = ensure_codex_marketplace_registered(
                    cwd=cwd,
                    codex_command=codex_command,
                    scope=codex_scope,
                )
                summary.codex_details.append(
                    f"codex mcp registration: {ensure_codex_mcp_registered(cwd=cwd, codex_command=codex_command)}"
                )
                summary.codex_reply_hook_status = remove_codex_reply_hook(cwd=cwd)
                summary.codex_details.extend(details)
            except Exception as exc:
                summary.codex_install_status = f"failed ({exc})"
                summary.codex_marketplace_status = "failed"
                summary.codex_reply_hook_status = "failed"
                summary.next_steps.append("Repair Hermit's Codex integration before relying on approvals or interview replies from Codex.")
        else:
            summary.codex_install_status = "skipped"

    if not summary.next_steps:
        summary.next_steps.append("Run your normal Hermit workflow.")
    return summary


def run_startup_self_heal(*, cwd: str) -> StartupHealSummary:
    summary = StartupHealSummary()
    settings_path = GLOBAL_SETTINGS_PATH
    if not settings_path.exists():
        init_settings_file(global_=True)
        summary.settings_initialized = True

    payload = _load_json(settings_path)
    api_key = str(payload.get("gateway_api_key") or "").strip()
    if not api_key or api_key == PLACEHOLDER_GATEWAY_KEY:
        created, _token = ensure_gateway_api_key(settings_path=settings_path)
        summary.gateway_api_key_created = created

    summary.gateway_status = ensure_gateway_running(cwd=cwd)
    summary.mcp_registration_status = inspect_claude_mcp_registration(entry=resolve_hermit_mcp_stdio_entry(cwd=cwd))
    summary.codex_runtime_status = "installed" if get_codex_runtime_version(cwd=cwd) else "missing"
    return summary


def format_startup_heal_summary(summary: StartupHealSummary) -> str:
    lines = ["[Hermit startup self-heal]"]
    if summary.settings_initialized:
        lines.append("- initialized global settings")
    if summary.gateway_api_key_created:
        lines.append("- created gateway API key")
    if summary.gateway_status in {"started", "healthy"}:
        lines.append(f"- gateway {summary.gateway_status}")
    if summary.mcp_registration_status == "missing":
        lines.append("- Claude MCP registration missing; run `hermit install` to repair it")
    if summary.codex_runtime_status == "missing":
        lines.append("- Hermit's Codex integration is missing; run `hermit install` to provision it")
    return "\n".join(lines)
