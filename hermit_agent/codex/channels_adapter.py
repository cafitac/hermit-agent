from __future__ import annotations

import json
import os
import re
import select
import shutil
import subprocess
import tarfile
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.request import urlopen
from ..version import VERSION


DEFAULT_STATE_FILE = ".codex-channels/state.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4317
DEFAULT_TIMEOUT_MS = 300_000
DEFAULT_NPX = "npx"
DEFAULT_PACKAGE_SPEC = "@cafitac/codex-channels@0.1.31"
DEFAULT_RUNTIME_DIR = ".hermit/codex-channels-runtime"
DEFAULT_PLUGIN_DIR = "plugins/codex-channels"
DEFAULT_SOURCE_CANDIDATES = (
    "../codex-channels",
    "../../codex-channels",
)
LOCAL_WORKSPACES = (
    "packages/core",
    "packages/persistence-file",
    "packages/backend-local",
    "packages/transport-codex-app-server",
    "packages/cli",
)
PLUGIN_SKILL = """---
name: codex-channels
description: Use the local codex-channels runtime for Codex-first interaction routing.
---

# codex-channels

This plugin was bootstrapped by Hermit so Codex can discover the local codex-channels bridge.

- local runtime only by default
- approvals, user input, and interaction replies flow through the packaged codex-channels runtime
- remote backends remain optional and out of the critical path
"""


@dataclass(frozen=True)
class CodexChannelsSettings:
    enabled: bool = False
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    state_file: str = DEFAULT_STATE_FILE
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    npx_command: str = DEFAULT_NPX
    source_path: str | None = None
    package_spec: str = DEFAULT_PACKAGE_SPEC
    runtime_dir: str = DEFAULT_RUNTIME_DIR
    plugin_dir: str = DEFAULT_PLUGIN_DIR


@dataclass(frozen=True)
class InstallCodexReport:
    install_command: list[str]
    serve_command: list[str]
    status_command: list[str]
    settings_path: str
    marketplace_path: str
    state_file: str
    plugin_path: str
    runtime_dir: str
    package_spec: str
    source_path: str | None
    install_mode: str


def _resolve_source_path(explicit: str | None, cwd: str) -> str | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("HERMIT_CODEX_CHANNELS_SOURCE_PATH", "").strip()
    if env:
        candidates.append(Path(env))
    base = Path(cwd)
    for candidate in DEFAULT_SOURCE_CANDIDATES:
        candidates.append((base / candidate).resolve())

    for candidate_path in candidates:
        root_path = candidate_path.expanduser().resolve()
        if (root_path / "packages" / "cli" / "dist" / "index.js").exists():
            return str(root_path)
    return None


def _resolve_path(value: str, cwd: str) -> str:
    path = Path(value)
    return str(path if path.is_absolute() else (Path(cwd) / path).resolve())


def _package_version(package_spec: str) -> str:
    match = re.search(r"@([0-9]+\.[0-9]+\.[0-9]+)$", package_spec)
    if not match:
        raise RuntimeError(f"Cannot derive codex-channels version from package spec: {package_spec}")
    return match.group(1)


def _normalize_package_spec(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return DEFAULT_PACKAGE_SPEC
    if re.search(r"@[0-9]+\.[0-9]+\.[0-9]+$", raw):
        return raw
    package_name = DEFAULT_PACKAGE_SPEC.rsplit("@", 1)[0]
    default_version = _package_version(DEFAULT_PACKAGE_SPEC)
    return f"{raw or package_name}@{default_version}"


def load_codex_channels_settings(cfg: dict[str, Any] | None, cwd: str) -> CodexChannelsSettings:
    raw = cfg or {}
    block = raw.get("codex_channels") if isinstance(raw, dict) and isinstance(raw.get("codex_channels"), dict) else raw
    if not isinstance(block, dict):
        block = {}

    state_file = _resolve_path(str(block.get("state_file") or DEFAULT_STATE_FILE), cwd)
    runtime_dir = _resolve_path(str(block.get("runtime_dir") or DEFAULT_RUNTIME_DIR), cwd)
    plugin_dir = _resolve_path(str(block.get("plugin_dir") or DEFAULT_PLUGIN_DIR), cwd)
    source_path = _resolve_source_path(str(block.get("source_path") or "").strip() or None, cwd)

    package_value = block.get("package_spec") or block.get("package")

    return CodexChannelsSettings(
        enabled=bool(block.get("enabled", False)),
        host=str(block.get("host") or DEFAULT_HOST),
        port=int(block.get("port") or DEFAULT_PORT),
        state_file=state_file,
        timeout_ms=int(block.get("timeout_ms") or DEFAULT_TIMEOUT_MS),
        npx_command=str(block.get("npx_command") or DEFAULT_NPX),
        source_path=source_path,
        package_spec=_normalize_package_spec(str(package_value) if package_value else None),
        runtime_dir=runtime_dir,
        plugin_dir=plugin_dir,
    )


def build_interaction(
    *,
    task_id: str,
    kind: str,
    question: str,
    options: list[str],
    method: str | None,
    thread_id: str | None,
    turn_id: str | None,
    request_id: str | int | None,
) -> dict[str, Any]:
    interaction_id = f"hermit-{task_id}-{request_id if request_id is not None else kind}"
    return {
        "id": interaction_id,
        "kind": kind,
        "source": {"type": "runtime", "name": "hermit-agent"},
        "codex": {
            "threadId": thread_id,
            "turnId": turn_id,
            "requestId": request_id,
            "method": method,
        },
        "payload": {
            "message": question,
            "options": [{"label": item, "value": item} for item in (options or [])],
            "metadata": {"taskId": task_id, "waitingKind": kind},
        },
        "policy": {
            "allowFreeText": kind in {"user_input_request", "elicitation_request"},
            "timeoutSec": DEFAULT_TIMEOUT_MS // 1000,
        },
    }


def _source_cli_entry(source_path: str) -> str:
    return str(Path(source_path) / "packages" / "cli" / "dist" / "index.js")


def _installed_cli_entry(settings: CodexChannelsSettings) -> str:
    return str(Path(settings.runtime_dir) / "node_modules" / "@cafitac" / "codex-channels" / "dist" / "index.js")


def _resolve_cli_entry(settings: CodexChannelsSettings) -> str:
    installed = Path(_installed_cli_entry(settings))
    if installed.exists():
        return str(installed)
    if settings.source_path:
        source_entry = Path(_source_cli_entry(settings.source_path))
        if source_entry.exists():
            return str(source_entry)
    raise RuntimeError("codex-channels CLI entry not found")


def build_runtime_install_command(*, settings: CodexChannelsSettings) -> list[str]:
    return [
        "npm",
        "install",
        "--no-save",
        "--prefix",
        settings.runtime_dir,
        settings.package_spec,
    ]


def build_runtime_local_install_command(*, settings: CodexChannelsSettings, source_path: str | None = None) -> list[str]:
    root_str = source_path or settings.source_path
    if not root_str:
        raise RuntimeError("codex-channels source path not found")
    root_path = Path(root_str)
    return [
        "npm",
        "install",
        "--no-save",
        "--prefix",
        settings.runtime_dir,
        *[str(root_path / workspace) for workspace in LOCAL_WORKSPACES],
    ]


def build_runtime_serve_command(*, settings: CodexChannelsSettings) -> list[str]:
    return [
        "node",
        _resolve_cli_entry(settings),
        "serve",
        "--host",
        settings.host,
        "--port",
        str(settings.port),
        "--state-file",
        settings.state_file,
    ]


def build_runtime_status_command(*, settings: CodexChannelsSettings) -> list[str]:
    return [
        "node",
        _resolve_cli_entry(settings),
        "status",
        "--host",
        settings.host,
        "--port",
        str(settings.port),
    ]


def build_runtime_submit_command(*, settings: CodexChannelsSettings, interaction_file: str) -> list[str]:
    return [
        "node",
        _resolve_cli_entry(settings),
        "submit",
        "--host",
        settings.host,
        "--port",
        str(settings.port),
        "--state-file",
        settings.state_file,
        "--interaction-file",
        interaction_file,
        "--timeout-ms",
        str(settings.timeout_ms),
    ]


def _write_plugin_wrapper(cwd: str, settings: CodexChannelsSettings) -> Path:
    plugin_dir = Path(settings.plugin_dir)
    (plugin_dir / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "skills" / "codex-channels").mkdir(parents=True, exist_ok=True)

    plugin_manifest = {
        "name": "codex-channels",
        "version": VERSION,
        "description": "Local-first interaction runtime for Codex-first workflows.",
        "skills": "./skills/",
        "mcpServers": "./.mcp.json",
        "interface": {
            "displayName": "codex-channels",
            "shortDescription": "Local-first interaction runtime for Codex",
            "category": "Coding",
            "capabilities": ["Interactive", "Write"],
        },
    }
    (plugin_dir / ".codex-plugin" / "plugin.json").write_text(json.dumps(plugin_manifest, indent=2) + "\n", encoding="utf-8")

    mcp = {
        "mcpServers": {
            "codex-channels-local": {
                "command": "node",
                "args": [
                    _resolve_cli_entry(settings),
                    "bridge-stdio",
                    "--quiet",
                    "--host",
                    settings.host,
                    "--port",
                    str(settings.port),
                    "--state-file",
                    settings.state_file,
                ],
                "env": {
                    "CODEX_CHANNELS_HOST": settings.host,
                    "CODEX_CHANNELS_PORT": str(settings.port),
                    "CODEX_CHANNELS_STATE_FILE": settings.state_file,
                },
            }
        }
    }
    (plugin_dir / ".mcp.json").write_text(json.dumps(mcp, indent=2) + "\n", encoding="utf-8")
    (plugin_dir / "skills" / "codex-channels" / "SKILL.md").write_text(PLUGIN_SKILL + "\n", encoding="utf-8")
    return plugin_dir


def _write_marketplace_entry(cwd: str, plugin_dir: Path) -> Path:
    marketplace_path = Path(cwd) / ".agents" / "plugins" / "marketplace.json"
    marketplace_path.parent.mkdir(parents=True, exist_ok=True)
    if marketplace_path.exists():
        try:
            payload = json.loads(marketplace_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    else:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("name", "local-workspace")
    payload.setdefault("interface", {"displayName": "Workspace Plugins"})
    plugins = payload.setdefault("plugins", [])
    entry = {
        "name": "codex-channels",
        "source": {"source": "local", "path": str(plugin_dir.resolve())},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Coding",
    }
    if isinstance(plugins, list):
        for idx, item in enumerate(plugins):
            if isinstance(item, dict) and item.get("name") == "codex-channels":
                plugins[idx] = entry
                break
        else:
            plugins.append(entry)
    payload["plugins"] = plugins
    marketplace_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return marketplace_path


def ensure_install_prereqs(codex_command: str) -> None:
    if shutil.which(codex_command) is None:
        raise RuntimeError(f"Codex command not found on PATH: {codex_command}")
    if shutil.which("node") is None:
        raise RuntimeError("node command not found on PATH")
    if shutil.which("npm") is None:
        raise RuntimeError("npm command not found on PATH")


def _run_install_command(command: list[str], cwd: str) -> tuple[bool, str]:
    try:
        completed = subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)
        return True, (completed.stdout or "") + (completed.stderr or "")
    except subprocess.CalledProcessError as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        return False, output.strip()


def _download_release_source(settings: CodexChannelsSettings) -> str:
    version = _package_version(settings.package_spec)
    downloads_dir = Path(settings.runtime_dir) / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    archive_path = downloads_dir / f"codex-channels-v{version}.tar.gz"
    url = f"https://github.com/cafitac/codex-channels/archive/refs/tags/v{version}.tar.gz"
    with urlopen(url) as response, open(archive_path, "wb") as handle:
        handle.write(response.read())

    source_root = Path(settings.runtime_dir) / "source"
    if source_root.exists():
        shutil.rmtree(source_root)
    source_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(source_root)
    extracted = next((item for item in source_root.iterdir() if item.is_dir()), None)
    if extracted is None:
        raise RuntimeError("Failed to extract codex-channels source archive")
    return str(extracted)


def _prepare_downloaded_source(settings: CodexChannelsSettings) -> str:
    extracted = _download_release_source(settings)
    for info_file in Path(extracted).glob("packages/*/tsconfig.tsbuildinfo"):
        info_file.unlink(missing_ok=True)
    subprocess.run(["npm", "install"], cwd=extracted, check=True, capture_output=True, text=True)
    subprocess.run(["npm", "run", "build"], cwd=extracted, check=True, capture_output=True, text=True)
    return extracted


def install_runtime_package(*, settings: CodexChannelsSettings, cwd: str) -> tuple[str, list[str], str | None]:
    Path(settings.runtime_dir).mkdir(parents=True, exist_ok=True)

    package_command = build_runtime_install_command(settings=settings)
    ok, output = _run_install_command(package_command, cwd)
    if ok and Path(_installed_cli_entry(settings)).exists():
        return "package", package_command, None

    if settings.source_path and Path(_source_cli_entry(settings.source_path)).exists():
        return "local-source", ["use-existing-source", settings.source_path], settings.source_path

    downloaded_source = _prepare_downloaded_source(settings)
    if Path(_source_cli_entry(downloaded_source)).exists():
        return "downloaded-source", ["download-and-build-source", downloaded_source], downloaded_source

    raise RuntimeError(output or "failed to install codex-channels runtime")


def write_codex_channels_settings(cwd: str, *, settings: CodexChannelsSettings, codex_command: str) -> Path:
    settings_path = Path(cwd) / ".hermit" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {}
    if settings_path.exists():
        try:
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    payload["codex_command"] = payload.get("codex_command") or codex_command
    payload["codex_channels"] = {
        "enabled": True,
        "host": settings.host,
        "port": settings.port,
        "state_file": settings.state_file,
        "timeout_ms": settings.timeout_ms,
        "npx_command": settings.npx_command,
        "source_path": settings.source_path or "",
        "package_spec": settings.package_spec,
        "runtime_dir": settings.runtime_dir,
        "plugin_dir": settings.plugin_dir,
    }
    settings_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return settings_path


def remove_codex_channels_settings(cwd: str) -> Path | None:
    settings_path = Path(cwd) / ".hermit" / "settings.json"
    if not settings_path.exists():
        return None
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return settings_path
    payload.pop("codex_channels", None)
    settings_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return settings_path


def remove_marketplace_plugin_entry(cwd: str, plugin_name: str = "codex-channels") -> Path | None:
    marketplace_path = Path(cwd) / ".agents" / "plugins" / "marketplace.json"
    if not marketplace_path.exists():
        return None
    try:
        payload = json.loads(marketplace_path.read_text(encoding="utf-8"))
    except Exception:
        return marketplace_path
    plugins = payload.get("plugins")
    if isinstance(plugins, list):
        payload["plugins"] = [item for item in plugins if not (isinstance(item, dict) and item.get("name") == plugin_name)]
        marketplace_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return marketplace_path


def remove_plugin_dir(cwd: str) -> Path:
    settings = load_codex_channels_settings({}, cwd)
    plugin_dir = Path(settings.plugin_dir)
    if plugin_dir.exists():
        shutil.rmtree(plugin_dir)
    return plugin_dir


def remove_runtime_dir(cwd: str) -> Path:
    settings = load_codex_channels_settings({}, cwd)
    runtime_dir = Path(settings.runtime_dir)
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    return runtime_dir


class CodexChannelsWaitSession:
    def __init__(self, *, settings: CodexChannelsSettings, interaction: dict[str, Any]) -> None:
        self._settings = settings
        self._interaction = interaction
        self._process: subprocess.Popen[str] | None = None

    def start(self) -> None:
        self._process = subprocess.Popen(
            build_runtime_submit_command(settings=self._settings, interaction_file="-"),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(self._interaction, ensure_ascii=False))
        self._process.stdin.close()

    def poll_response(self) -> str | None:
        if self._process is None or self._process.stdout is None:
            return None
        ready, _, _ = select.select([self._process.stdout], [], [], 0)
        if not ready:
            return None
        line = self._process.stdout.readline()
        if not line:
            return None
        payload = json.loads(line)
        response = payload.get("response") or {}
        action = str(response.get("action") or "")
        values = response.get("values") or []
        if values:
            return str(values[0])
        if action == "accept":
            return "yes"
        if action == "decline":
            return "no"
        if action == "cancel":
            return "cancel"
        return action or None

    def terminate(self) -> None:
        proc = self._process
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        self._process = None


def install_codex_channels(*, cwd: str, codex_command: str = "codex", scope: str = "workspace") -> InstallCodexReport:
    settings = load_codex_channels_settings({}, cwd)
    ensure_install_prereqs(codex_command)
    install_mode, install_command, source_path = install_runtime_package(settings=settings, cwd=cwd)
    if source_path and source_path != settings.source_path:
        settings = replace(settings, source_path=source_path)
    plugin_path = _write_plugin_wrapper(cwd, settings)
    marketplace_path = _write_marketplace_entry(cwd, plugin_path)
    settings_path = write_codex_channels_settings(cwd, settings=settings, codex_command=codex_command)

    serve_command = build_runtime_serve_command(settings=settings)
    status_command = build_runtime_status_command(settings=settings)
    proc = subprocess.Popen(serve_command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                subprocess.run(status_command, cwd=cwd, check=True, capture_output=True, text=True, timeout=5)
                break
            except Exception:
                time.sleep(0.25)
        else:
            raise RuntimeError("codex-channels runtime smoke check failed")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    return InstallCodexReport(
        install_command=install_command,
        serve_command=serve_command,
        status_command=status_command,
        settings_path=str(settings_path),
        marketplace_path=str(marketplace_path),
        state_file=settings.state_file,
        plugin_path=str(plugin_path),
        runtime_dir=settings.runtime_dir,
        package_spec=settings.package_spec,
        source_path=source_path,
        install_mode=install_mode,
    )
