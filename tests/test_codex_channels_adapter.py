from __future__ import annotations

import json
from pathlib import Path

from hermit_agent.codex_channels_adapter import (
    CodexChannelsSettings,
    build_interaction,
    build_runtime_install_command,
    build_runtime_local_install_command,
    build_runtime_serve_command,
    build_runtime_status_command,
    build_runtime_submit_command,
    install_codex_channels,
    remove_codex_channels_settings,
    remove_marketplace_plugin_entry,
    remove_plugin_dir,
    remove_runtime_dir,
    write_codex_channels_settings,
)


def _make_source_repo(tmp_path: Path) -> Path:
    source = tmp_path / "codex-channels"
    (source / "packages" / "cli" / "dist").mkdir(parents=True)
    (source / "packages" / "cli" / "dist" / "index.js").write_text("console.log(\'ok\')\n", encoding="utf-8")
    for workspace in (
        "packages/core",
        "packages/persistence-file",
        "packages/backend-local",
        "packages/transport-codex-app-server",
        "packages/cli",
    ):
        package_dir = source / workspace
        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / "package.json").write_text("{}\n", encoding="utf-8")
    return source


def test_build_interaction_preserves_correlation_fields():
    interaction = build_interaction(
        task_id="task-1",
        kind="approval_request",
        question="Allow this command?",
        options=["Yes", "No"],
        method="item/commandExecution/requestApproval",
        thread_id="thr-1",
        turn_id="turn-1",
        request_id="req-1",
    )

    assert interaction["id"] == "hermit-task-1-req-1"
    assert interaction["kind"] == "approval_request"
    assert interaction["codex"] == {
        "threadId": "thr-1",
        "turnId": "turn-1",
        "requestId": "req-1",
        "method": "item/commandExecution/requestApproval",
    }


def test_write_codex_channels_settings_enables_defaults(tmp_path: Path):
    settings = CodexChannelsSettings(
        enabled=True,
        state_file=str(tmp_path / ".codex-channels/state.json"),
        runtime_dir=str(tmp_path / ".hermit/codex-channels-runtime"),
        plugin_dir=str(tmp_path / "plugins/codex-channels"),
        package_spec="@cafitac/codex-channels@0.1.9",
    )
    path = write_codex_channels_settings(str(tmp_path), settings=settings, codex_command="codex")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["codex_command"] == "codex"
    assert payload["codex_channels"]["enabled"] is True
    assert payload["codex_channels"]["state_file"] == str(tmp_path / ".codex-channels/state.json")
    assert payload["codex_channels"]["runtime_dir"] == str(tmp_path / ".hermit/codex-channels-runtime")
    assert payload["codex_channels"]["plugin_dir"] == str(tmp_path / "plugins/codex-channels")
    assert payload["codex_channels"]["package_spec"] == "@cafitac/codex-channels@0.1.9"


def test_install_codex_channels_falls_back_to_downloaded_source(monkeypatch, tmp_path: Path):
    source = _make_source_repo(tmp_path)
    monkeypatch.setattr("shutil.which", lambda cmd: f"/usr/bin/{cmd}")

    runs: list[list[str]] = []
    spawned: list[list[str]] = []

    class DummyProc:
        def poll(self):
            return None
        def terminate(self):
            return None
        def wait(self, timeout=None):
            return 0

    def fake_run(args, **kwargs):
        runs.append(args)
        runtime_dir = tmp_path / ".hermit" / "codex-channels-runtime" / "node_modules" / "@cafitac" / "codex-channels" / "dist"
        if args[:4] == ["npm", "install", "--no-save", "--prefix"] and "@cafitac/codex-channels@0.1.9" in args:
            return type("Completed", (), {"stdout": "ok", "stderr": "", "returncode": 0})()
        if args[:2] == ["npm", "install"] and str(source) in kwargs.get("cwd", ""):
            return type("Completed", (), {"stdout": "ok", "stderr": "", "returncode": 0})()
        if args[:3] == ["npm", "run", "build"]:
            return type("Completed", (), {"stdout": "ok", "stderr": "", "returncode": 0})()
        runtime_dir.mkdir(parents=True, exist_ok=True)
        (runtime_dir / "index.js").write_text("console.log(\'ok\')\n", encoding="utf-8")
        return type("Completed", (), {"stdout": "ok", "stderr": "", "returncode": 0})()

    def fake_popen(args, **kwargs):
        spawned.append(args)
        return DummyProc()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr("hermit_agent.codex_channels_adapter._download_release_source", lambda settings: str(source))

    report = install_codex_channels(cwd=str(tmp_path), codex_command="codex", scope="workspace")

    settings = CodexChannelsSettings(
        state_file=str(tmp_path / ".codex-channels/state.json"),
        runtime_dir=str(tmp_path / ".hermit/codex-channels-runtime"),
        plugin_dir=str(tmp_path / "plugins/codex-channels"),
        package_spec="@cafitac/codex-channels@0.1.9",
    )
    resolved_settings = CodexChannelsSettings(
        state_file=str(tmp_path / ".codex-channels/state.json"),
        runtime_dir=str(tmp_path / ".hermit/codex-channels-runtime"),
        plugin_dir=str(tmp_path / "plugins/codex-channels"),
        package_spec="@cafitac/codex-channels@0.1.9",
        source_path=str(source),
    )
    assert runs[0] == build_runtime_install_command(settings=settings)
    assert runs[1] == ["npm", "install"]
    assert runs[2] == ["npm", "run", "build"]
    assert spawned[0][0] == "node"
    assert spawned[0][1] == str(source / "packages" / "cli" / "dist" / "index.js")
    assert spawned[0][2:] == ["serve", "--host", "127.0.0.1", "--port", "4317", "--state-file", str(tmp_path / ".codex-channels/state.json")]
    assert runs[3][0] == "node"
    assert runs[3][1] == str(source / "packages" / "cli" / "dist" / "index.js")
    assert runs[3][2:] == ["status", "--host", "127.0.0.1", "--port", "4317"]
    assert report.install_mode == "downloaded-source"
    assert report.source_path == str(source)


def test_build_runtime_submit_command_uses_installed_cli_entry(tmp_path: Path):
    runtime_dir = tmp_path / ".hermit" / "codex-channels-runtime" / "node_modules" / "@cafitac" / "codex-channels" / "dist"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "index.js").write_text("console.log(\'ok\')\n", encoding="utf-8")
    settings = CodexChannelsSettings(
        state_file=str(tmp_path / ".codex-channels/state.json"),
        runtime_dir=str(tmp_path / ".hermit/codex-channels-runtime"),
        package_spec="@cafitac/codex-channels@0.1.9",
    )
    command = build_runtime_submit_command(settings=settings, interaction_file=str(tmp_path / "interaction.json"))
    assert command[:3] == ["node", str(runtime_dir / "index.js"), "submit"]
    assert "--interaction-file" in command


def test_remove_codex_channels_assets(tmp_path: Path):
    settings_path = tmp_path / ".hermit" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"codex_channels": {"enabled": True}, "model": "gpt-5.4"}) + "\n", encoding="utf-8")

    marketplace_path = tmp_path / ".agents" / "plugins" / "marketplace.json"
    marketplace_path.parent.mkdir(parents=True)
    marketplace_path.write_text(json.dumps({"plugins": [{"name": "codex-channels"}, {"name": "other"}]}, indent=2) + "\n", encoding="utf-8")

    plugin_dir = tmp_path / "plugins" / "codex-channels"
    plugin_dir.mkdir(parents=True)
    runtime_dir = tmp_path / ".hermit" / "codex-channels-runtime"
    runtime_dir.mkdir(parents=True)

    remove_codex_channels_settings(str(tmp_path))
    remove_marketplace_plugin_entry(str(tmp_path))
    remove_plugin_dir(str(tmp_path))
    remove_runtime_dir(str(tmp_path))

    settings_payload = json.loads(settings_path.read_text(encoding="utf-8"))
    marketplace_payload = json.loads(marketplace_path.read_text(encoding="utf-8"))
    assert "codex_channels" not in settings_payload
    assert marketplace_payload["plugins"] == [{"name": "other"}]
    assert not plugin_dir.exists()
    assert not runtime_dir.exists()
