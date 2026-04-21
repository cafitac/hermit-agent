from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_STATE_FILE = ".codex-channels/state.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4317
DEFAULT_TIMEOUT_MS = 300_000
DEFAULT_NPX = "npx"
DEFAULT_SOURCE_CANDIDATES = (
    "../codex-channels",
    "../../codex-channels",
)


@dataclass(frozen=True)
class CodexChannelsSettings:
    enabled: bool = False
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    state_file: str = DEFAULT_STATE_FILE
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    npx_command: str = DEFAULT_NPX
    source_path: str | None = None


@dataclass(frozen=True)
class InstallCodexReport:
    bootstrap_command: list[str]
    serve_command: list[str]
    status_command: list[str]
    settings_path: str
    marketplace_path: str
    state_file: str
    source_path: str


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

    for candidate in candidates:
        root = candidate.expanduser().resolve()
        if (root / ".codex-plugin" / "plugin.json").exists() and (root / "packages" / "cli" / "dist" / "index.js").exists():
            return str(root)
    return None


def load_codex_channels_settings(cfg: dict[str, Any] | None, cwd: str) -> CodexChannelsSettings:
    raw = cfg or {}
    block = raw.get("codex_channels") if isinstance(raw, dict) and isinstance(raw.get("codex_channels"), dict) else raw
    if not isinstance(block, dict):
        block = {}

    state_file = str(block.get("state_file") or DEFAULT_STATE_FILE)
    if not os.path.isabs(state_file):
        state_file = str(Path(cwd) / state_file)

    source_path = _resolve_source_path(
        str(block.get("source_path") or "").strip() or None,
        cwd,
    )

    return CodexChannelsSettings(
        enabled=bool(block.get("enabled", False)),
        host=str(block.get("host") or DEFAULT_HOST),
        port=int(block.get("port") or DEFAULT_PORT),
        state_file=state_file,
        timeout_ms=int(block.get("timeout_ms") or DEFAULT_TIMEOUT_MS),
        npx_command=str(block.get("npx_command") or DEFAULT_NPX),
        source_path=source_path,
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
    policy_allow_free_text = kind in {"user_input_request", "elicitation_request"}
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
        "policy": {"allowFreeText": policy_allow_free_text, "timeoutSec": DEFAULT_TIMEOUT_MS // 1000},
    }


def _cli_entry(source_path: str) -> str:
    return str(Path(source_path) / "packages" / "cli" / "dist" / "index.js")


def build_plugin_bootstrap_command(
    *,
    settings: CodexChannelsSettings,
    scope: str,
    cwd: str,
) -> list[str]:
    if not settings.source_path:
        raise RuntimeError("codex-channels source path not found")
    return [
        "node",
        _cli_entry(settings.source_path),
        "plugin-bootstrap",
        "--scope",
        scope,
        "--plugin-path",
        settings.source_path,
        "--marketplace-file",
        str(Path(cwd) / ".agents" / "plugins" / "marketplace.json"),
    ]


def build_runtime_serve_command(*, settings: CodexChannelsSettings) -> list[str]:
    if not settings.source_path:
        raise RuntimeError("codex-channels source path not found")
    return [
        "node",
        _cli_entry(settings.source_path),
        "serve",
        "--host",
        settings.host,
        "--port",
        str(settings.port),
        "--state-file",
        settings.state_file,
    ]


def build_runtime_status_command(*, settings: CodexChannelsSettings) -> list[str]:
    if not settings.source_path:
        raise RuntimeError("codex-channels source path not found")
    return [
        "node",
        _cli_entry(settings.source_path),
        "status",
        "--host",
        settings.host,
        "--port",
        str(settings.port),
    ]


def build_runtime_submit_command(*, settings: CodexChannelsSettings, interaction_file: str) -> list[str]:
    if not settings.source_path:
        raise RuntimeError("codex-channels source path not found")
    return [
        "node",
        _cli_entry(settings.source_path),
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


def ensure_install_prereqs(codex_command: str, settings: CodexChannelsSettings) -> None:
    if shutil.which(codex_command) is None:
        raise RuntimeError(f"Codex command not found on PATH: {codex_command}")
    if shutil.which("node") is None:
        raise RuntimeError("node command not found on PATH")
    if not settings.source_path:
        raise RuntimeError(
            "codex-channels source path not found. Set HERMIT_CODEX_CHANNELS_SOURCE_PATH or place the repo next to claude-code."
        )


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
        "state_file": os.path.relpath(settings.state_file, cwd),
        "timeout_ms": settings.timeout_ms,
        "npx_command": settings.npx_command,
        "source_path": os.path.relpath(settings.source_path, cwd) if settings.source_path else "",
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


class CodexChannelsWaitSession:
    def __init__(self, *, settings: CodexChannelsSettings, interaction: dict[str, Any]) -> None:
        self._settings = settings
        self._interaction = interaction
        self._process: subprocess.Popen[str] | None = None
        self._interaction_file: str | None = None

    def start(self) -> None:
        if not self._settings.source_path:
            raise RuntimeError("codex-channels source path not configured")
        fd, interaction_file = tempfile.mkstemp(prefix="hermit-codex-channels-", suffix=".json")
        os.close(fd)
        Path(interaction_file).write_text(json.dumps(self._interaction, ensure_ascii=False), encoding="utf-8")
        self._interaction_file = interaction_file
        self._process = subprocess.Popen(
            build_runtime_submit_command(settings=self._settings, interaction_file=interaction_file),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self._settings.source_path,
        )

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
        if self._interaction_file:
            try:
                Path(self._interaction_file).unlink(missing_ok=True)
            except Exception:
                pass
            self._interaction_file = None


def install_codex_channels(*, cwd: str, codex_command: str = "codex", scope: str = "workspace") -> InstallCodexReport:
    settings = load_codex_channels_settings({}, cwd)
    ensure_install_prereqs(codex_command, settings)
    settings_path = write_codex_channels_settings(cwd, settings=settings, codex_command=codex_command)

    bootstrap_command = build_plugin_bootstrap_command(settings=settings, scope=scope, cwd=cwd)
    subprocess.run(bootstrap_command, cwd=cwd, check=True, capture_output=True, text=True)

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

    marketplace_path = Path(cwd) / ".agents" / "plugins" / "marketplace.json"
    return InstallCodexReport(
        bootstrap_command=bootstrap_command,
        serve_command=serve_command,
        status_command=status_command,
        settings_path=str(settings_path),
        marketplace_path=str(marketplace_path),
        state_file=settings.state_file,
        source_path=settings.source_path,
    )
