from __future__ import annotations

import json
from pathlib import Path

from hermit_agent.codex_channels_adapter import (
    CodexChannelsSettings,
    build_interaction,
    build_plugin_bootstrap_command,
    build_runtime_serve_command,
    build_runtime_status_command,
    build_runtime_submit_command,
    install_codex_channels,
    remove_codex_channels_settings,
    remove_marketplace_plugin_entry,
    write_codex_channels_settings,
)


def _make_source_repo(tmp_path: Path) -> Path:
    source = tmp_path / "codex-channels"
    (source / ".codex-plugin").mkdir(parents=True)
    (source / ".codex-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    (source / "packages" / "cli" / "dist").mkdir(parents=True)
    (source / "packages" / "cli" / "dist" / "index.js").write_text("console.log('ok')\n", encoding="utf-8")
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
    assert interaction["payload"]["options"] == [
        {"label": "Yes", "value": "Yes"},
        {"label": "No", "value": "No"},
    ]


def test_write_codex_channels_settings_enables_defaults(tmp_path: Path):
    source = _make_source_repo(tmp_path)
    settings = CodexChannelsSettings(enabled=True, state_file=str(tmp_path / ".codex-channels/state.json"), source_path=str(source))
    path = write_codex_channels_settings(str(tmp_path), settings=settings, codex_command="codex")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["codex_command"] == "codex"
    assert payload["codex_channels"]["enabled"] is True
    assert payload["codex_channels"]["state_file"] == ".codex-channels/state.json"
    assert payload["codex_channels"]["source_path"] == "codex-channels"


def test_install_codex_channels_runs_bootstrap_and_smoke(monkeypatch, tmp_path: Path):
    source = _make_source_repo(tmp_path)
    monkeypatch.setenv("HERMIT_CODEX_CHANNELS_SOURCE_PATH", str(source))
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
        return type("Completed", (), {"stdout": "ok", "stderr": "", "returncode": 0})()

    def fake_popen(args, **kwargs):
        spawned.append(args)
        return DummyProc()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("subprocess.Popen", fake_popen)

    report = install_codex_channels(cwd=str(tmp_path), codex_command="codex", scope="workspace")

    assert runs[0] == build_plugin_bootstrap_command(
        settings=CodexChannelsSettings(state_file=str(tmp_path / ".codex-channels/state.json"), source_path=str(source)),
        scope="workspace",
        cwd=str(tmp_path),
    )
    assert spawned[0] == build_runtime_serve_command(
        settings=CodexChannelsSettings(state_file=str(tmp_path / ".codex-channels/state.json"), source_path=str(source)),
    )
    assert runs[1] == build_runtime_status_command(
        settings=CodexChannelsSettings(state_file=str(tmp_path / ".codex-channels/state.json"), source_path=str(source)),
    )
    assert report.settings_path.endswith(".hermit/settings.json")
    assert report.source_path == str(source)


def test_build_runtime_submit_command_uses_cli_submit_entry(tmp_path: Path):
    source = _make_source_repo(tmp_path)
    settings = CodexChannelsSettings(state_file=str(tmp_path / ".codex-channels/state.json"), source_path=str(source))
    command = build_runtime_submit_command(settings=settings, interaction_file=str(tmp_path / "interaction.json"))
    assert command[:3] == ["node", str(source / "packages" / "cli" / "dist" / "index.js"), "submit"]
    assert "--interaction-file" in command


def test_remove_codex_channels_settings_and_marketplace_entry(tmp_path: Path):
    settings_path = tmp_path / ".hermit" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"codex_channels": {"enabled": True}, "model": "gpt-5.4"}) + "\n", encoding="utf-8")

    marketplace_path = tmp_path / ".agents" / "plugins" / "marketplace.json"
    marketplace_path.parent.mkdir(parents=True)
    marketplace_path.write_text(
        json.dumps({"plugins": [{"name": "codex-channels"}, {"name": "other"}]}, indent=2) + "\n",
        encoding="utf-8",
    )

    remove_codex_channels_settings(str(tmp_path))
    remove_marketplace_plugin_entry(str(tmp_path))

    settings_payload = json.loads(settings_path.read_text(encoding="utf-8"))
    marketplace_payload = json.loads(marketplace_path.read_text(encoding="utf-8"))
    assert "codex_channels" not in settings_payload
    assert marketplace_payload["plugins"] == [{"name": "other"}]
