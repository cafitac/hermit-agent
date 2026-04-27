from __future__ import annotations

import json
from urllib.error import URLError

from hermit_agent.install_flow import (
    PLACEHOLDER_GATEWAY_KEY,
    InstallSummary,
    StartupHealSummary,
    configure_model_preferences,
    ensure_codex_mcp_registered,
    ensure_codex_channels_ready,
    ensure_codex_marketplace_registered,
    ensure_gateway_api_key,
    ensure_gateway_running,
    format_install_summary,
    format_startup_heal_summary,
    get_codex_runtime_version,
    inspect_claude_mcp_registration,
    probe_gateway_health,
    register_claude_mcp,
    resolve_hermit_mcp_stdio_entry,
    run_install,
    run_startup_self_heal,
)


def test_format_install_summary_includes_key_sections():
    summary = InstallSummary(
        settings_path="/tmp/settings.json",
        model_selection_status="auto (glm-5.1, gpt-5.4)",
        gateway_api_key_created=True,
        gateway_api_key_present=True,
        mcp_registration_status="registered",
        mcp_registration_path="/tmp/.claude.json",
        codex_install_status="installed",
        codex_marketplace_status="registered",
        codex_reply_hook_status="registered",
        codex_details=["runtime dir: /tmp/runtime"],
        next_steps=["Run Hermit."],
    )

    text = format_install_summary(summary)

    assert "Hermit install is ready." in text
    assert "- settings file: /tmp/settings.json" in text
    assert "- model selection: auto (glm-5.1, gpt-5.4)" in text
    assert "- gateway API key: created" in text
    assert "- gateway: unchecked" in text
    assert "- MCP registration: registered" in text
    assert "- Codex integration: installed" in text
    assert "- Codex marketplace registration: registered" in text
    assert "- Legacy Codex reply hook: registered" in text
    assert "runtime dir: /tmp/runtime" in text
    assert "1. Run Hermit." in text


def test_register_claude_mcp_writes_user_wide_stdio_entry(tmp_path):
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps({"mcpServers": {"other": {"type": "stdio", "command": "other"}}}), encoding="utf-8")

    status, path, backup = register_claude_mcp(
        command_path=tmp_path / "bin" / "mcp-server.sh",
        claude_json_path=claude_json,
    )

    payload = json.loads(claude_json.read_text(encoding="utf-8"))
    assert status == "registered"
    assert path == claude_json
    assert backup is not None and backup.exists()
    assert payload["mcpServers"]["hermit-channel"]["type"] == "stdio"
    assert payload["mcpServers"]["other"]["command"] == "other"


def test_register_claude_mcp_accepts_prebuilt_entry(tmp_path):
    claude_json = tmp_path / ".claude.json"
    entry = {"type": "stdio", "command": "hermit", "args": ["mcp-server"]}

    status, path, backup = register_claude_mcp(entry=entry, claude_json_path=claude_json)

    payload = json.loads(claude_json.read_text(encoding="utf-8"))
    assert status == "registered"
    assert path == claude_json
    assert backup is None
    assert payload["mcpServers"]["hermit-channel"] == entry


def test_register_claude_mcp_repairs_invalid_json_by_resetting_to_clean_payload(tmp_path):
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text("{not-json", encoding="utf-8")

    status, path, backup = register_claude_mcp(
        command_path=tmp_path / "bin" / "mcp-server.sh",
        claude_json_path=claude_json,
    )

    payload = json.loads(claude_json.read_text(encoding="utf-8"))
    assert status == "registered"
    assert path == claude_json
    assert backup is not None and backup.exists()
    assert payload["mcpServers"]["hermit-channel"]["command"].endswith("mcp-server.sh")


def test_inspect_claude_mcp_registration_reports_missing_and_registered(tmp_path):
    command = tmp_path / "bin" / "mcp-server.sh"
    command.parent.mkdir(parents=True)
    command.write_text("", encoding="utf-8")
    claude_json = tmp_path / ".claude.json"

    assert inspect_claude_mcp_registration(command_path=command, claude_json_path=claude_json) == "missing"

    claude_json.write_text(json.dumps({"mcpServers": {"hermit-channel": {"type": "stdio", "command": str(command)}}}), encoding="utf-8")
    assert inspect_claude_mcp_registration(command_path=command, claude_json_path=claude_json) == "registered"


def test_resolve_hermit_mcp_stdio_entry_uses_stable_hermit_command():
    entry = resolve_hermit_mcp_stdio_entry(cwd="/tmp/demo")

    assert entry == {"type": "stdio", "command": "hermit", "args": ["mcp-server"]}


def test_ensure_codex_mcp_registered_replaces_mismatched_entry(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    monkeypatch.setattr(
        "hermit_agent.install_flow.resolve_hermit_mcp_stdio_entry",
        lambda *, cwd: {"type": "stdio", "command": "hermit", "args": ["mcp-server"]},
    )

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:4] == ["codex", "mcp", "get", "hermit-channel"]:
            return Result(
                returncode=0,
                stdout=json.dumps(
                    {
                        "transport": {
                            "command": "/Users/reddit/Project/claude-code/bin/mcp-server.sh",
                            "args": [],
                        }
                    }
                ),
            )
        if args[:4] == ["codex", "mcp", "remove", "hermit-channel"]:
            return Result(returncode=0)
        if args[:4] == ["codex", "mcp", "add", "hermit-channel"]:
            return Result(returncode=0)
        raise AssertionError(args)

    monkeypatch.setattr("hermit_agent.install_flow.subprocess.run", fake_run)

    status = ensure_codex_mcp_registered(cwd=str(tmp_path), codex_command="codex")

    assert status == "registered"
    assert calls == [
        ["codex", "mcp", "get", "hermit-channel", "--json"],
        ["codex", "mcp", "remove", "hermit-channel"],
        ["codex", "mcp", "add", "hermit-channel", "--", "hermit", "mcp-server"],
    ]


def test_ensure_gateway_api_key_creates_and_persists_key(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"gateway_api_key": PLACEHOLDER_GATEWAY_KEY}), encoding="utf-8")

    calls: list[tuple[str, str]] = []

    async def fake_init_db() -> None:
        return None

    async def fake_lookup_api_key(token: str) -> str | None:
        return None

    async def fake_create_api_key(api_key: str, user: str, *, grant_all_platforms: bool = False) -> None:
        calls.append((api_key, user))

    monkeypatch.setattr("hermit_agent.gateway.db.init_db", fake_init_db)
    monkeypatch.setattr("hermit_agent.gateway.db.lookup_api_key", fake_lookup_api_key)
    monkeypatch.setattr("hermit_agent.gateway.db.create_api_key", fake_create_api_key)

    created, api_key = ensure_gateway_api_key(settings_path=settings_path)

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert created is True
    assert payload["gateway_api_key"] == api_key
    assert calls == [(api_key, "local")]


def test_probe_gateway_health_returns_false_on_connection_errors(monkeypatch):
    monkeypatch.setattr(
        "hermit_agent.install_flow.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(URLError("down")),
    )

    assert probe_gateway_health() is False


def test_ensure_gateway_running_starts_daemon_when_probe_is_unhealthy(tmp_path, monkeypatch):
    gateway_script = tmp_path / "bin" / "gateway.sh"
    gateway_script.parent.mkdir(parents=True)
    gateway_script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    probes = iter([False, True])
    monkeypatch.setattr("hermit_agent.install_flow.probe_gateway_health", lambda timeout=2.0: next(probes))
    # Force fallback to bin/gateway.sh by pretending hermit-gateway is not in PATH
    monkeypatch.setattr("hermit_agent.install_flow.shutil.which", lambda name: None)

    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, **kwargs):
        calls.append(args)
        return Result()

    monkeypatch.setattr("hermit_agent.install_flow.subprocess.run", fake_run)

    status = ensure_gateway_running(cwd=str(tmp_path))

    assert status == "started"
    assert calls == [[str(gateway_script), "--daemon"]]


def test_get_codex_runtime_version_reads_installed_package_json(tmp_path, monkeypatch):
    runtime_pkg = tmp_path / ".hermit" / "codex-channels-runtime" / "node_modules" / "@cafitac" / "codex-channels"
    runtime_pkg.mkdir(parents=True)
    (runtime_pkg / "package.json").write_text(json.dumps({"version": "0.1.31"}), encoding="utf-8")

    class Settings:
        runtime_dir = str(tmp_path / ".hermit" / "codex-channels-runtime")
        package_spec = "@cafitac/codex-channels@0.1.31"

    monkeypatch.setattr("hermit_agent.codex_channels_adapter.load_codex_channels_settings", lambda cfg, cwd: Settings())
    monkeypatch.setattr("hermit_agent.install_flow.load_settings", lambda cwd=None: {})

    assert get_codex_runtime_version(cwd=str(tmp_path)) == "0.1.31"


def test_ensure_codex_channels_ready_reuses_healthy_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr("hermit_agent.install_flow.get_codex_runtime_version", lambda *, cwd: "0.1.31")
    monkeypatch.setattr("hermit_agent.install_flow._desired_codex_runtime_version", lambda *, cwd: "0.1.31")

    status, details, version = ensure_codex_channels_ready(cwd=str(tmp_path), codex_command="codex", scope="workspace")

    assert status == "healthy"
    assert version == "0.1.31"
    assert details == ["runtime version: 0.1.31"]


def test_ensure_codex_channels_ready_installs_when_runtime_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("hermit_agent.install_flow.get_codex_runtime_version", lambda *, cwd: None)
    monkeypatch.setattr("hermit_agent.install_flow._desired_codex_runtime_version", lambda *, cwd: "0.1.31")

    class DummyReport:
        install_mode = "package"
        runtime_dir = "/tmp/runtime"
        settings_path = "/tmp/settings.json"
        marketplace_path = "/tmp/marketplace.json"

    monkeypatch.setattr("hermit_agent.codex_channels_adapter.install_codex_channels", lambda **kwargs: DummyReport())
    versions = iter([None, "0.1.31"])
    monkeypatch.setattr("hermit_agent.install_flow.get_codex_runtime_version", lambda *, cwd: next(versions))

    status, details, version = ensure_codex_channels_ready(cwd=str(tmp_path), codex_command="codex", scope="workspace")

    assert status == "installed"
    assert version == "0.1.31"
    assert any("runtime dir: /tmp/runtime" == item for item in details)


def test_ensure_codex_marketplace_registered_adds_workspace_marketplace(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = f"Added marketplace `local-workspace` from {tmp_path}.\nInstalled marketplace root: {tmp_path}\n"
        stderr = ""

    def fake_run(args, **kwargs):
        calls.append(args)
        return Result()

    monkeypatch.setattr("hermit_agent.install_flow.subprocess.run", fake_run)

    status = ensure_codex_marketplace_registered(cwd=str(tmp_path), codex_command="codex", scope="workspace")

    assert status == "registered"
    assert calls == [["codex", "plugin", "marketplace", "add", str(tmp_path)]]


def test_ensure_codex_marketplace_registered_reports_unchanged(tmp_path, monkeypatch):
    class Result:
        returncode = 0
        stdout = f"Marketplace `local-workspace` is already added from {tmp_path}.\nInstalled marketplace root: {tmp_path}\n"
        stderr = ""

    monkeypatch.setattr("hermit_agent.install_flow.subprocess.run", lambda *args, **kwargs: Result())

    status = ensure_codex_marketplace_registered(cwd=str(tmp_path), codex_command="codex", scope="workspace")

    assert status == "unchanged"


def test_ensure_codex_marketplace_registered_uses_home_for_user_scope(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "Added marketplace `local`.\n"
        stderr = ""

    monkeypatch.setattr("hermit_agent.install_flow.subprocess.run", lambda args, **kwargs: calls.append(args) or Result())
    monkeypatch.setattr("hermit_agent.install_flow.Path.home", lambda: tmp_path / "home")

    status = ensure_codex_marketplace_registered(cwd=str(tmp_path), codex_command="codex", scope="user")

    assert status == "registered"
    assert calls == [["codex", "plugin", "marketplace", "add", str(tmp_path / "home")]]


def test_format_startup_heal_summary_mentions_missing_integrations():
    summary = StartupHealSummary(
        settings_initialized=True,
        gateway_api_key_created=True,
        gateway_status="started",
        mcp_registration_status="missing",
        codex_runtime_status="missing",
    )

    text = format_startup_heal_summary(summary)

    assert "initialized global settings" in text
    assert "created gateway API key" in text
    assert "gateway started" in text
    assert "Claude MCP registration missing" in text
    assert "Codex integration is missing" in text
    assert "Guided setup is recommended" in text


def test_startup_heal_summary_recommends_guided_install_for_missing_integrations():
    summary = StartupHealSummary(
        gateway_status="healthy",
        mcp_registration_status="missing",
        codex_runtime_status="installed",
    )

    assert summary.guided_install_recommended is True


def test_startup_heal_summary_is_healthy_when_gateway_and_integrations_are_ready():
    summary = StartupHealSummary(
        gateway_status="healthy",
        mcp_registration_status="registered",
        codex_runtime_status="installed",
    )

    assert summary.guided_install_recommended is False


def test_run_install_accepts_defaults_and_invokes_optional_steps(tmp_path, monkeypatch):
    global_settings = tmp_path / "global-settings.json"
    global_settings.write_text(json.dumps({"gateway_api_key": ""}), encoding="utf-8")
    monkeypatch.setattr("hermit_agent.config.GLOBAL_SETTINGS_PATH", global_settings)

    monkeypatch.setattr("hermit_agent.install_flow._prompt_yes_no", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        "hermit_agent.install_flow.configure_model_preferences",
        lambda **kwargs: "auto (gpt-5.4, glm-5.1, qwen3-coder:30b)",
    )
    monkeypatch.setattr(
        "hermit_agent.install_flow.ensure_gateway_api_key",
        lambda *, settings_path: (True, "hermit-mcp-test"),
    )
    monkeypatch.setattr("hermit_agent.install_flow.ensure_gateway_running", lambda *, cwd: "healthy")
    monkeypatch.setattr(
        "hermit_agent.install_flow.register_claude_mcp",
        lambda **kwargs: ("registered", tmp_path / ".claude.json", None),
    )

    class DummyReport:
        install_mode = "package"
        runtime_dir = "/tmp/runtime"
        settings_path = "/tmp/.hermit/settings.json"
        marketplace_path = "/tmp/.agents/plugins/marketplace.json"

    monkeypatch.setattr(
        "hermit_agent.install_flow.ensure_codex_channels_ready",
        lambda **kwargs: ("installed", ["runtime dir: /tmp/runtime"], "0.1.31"),
    )
    monkeypatch.setattr(
        "hermit_agent.install_flow.ensure_codex_marketplace_registered",
        lambda **kwargs: "registered",
    )
    monkeypatch.setattr(
        "hermit_agent.install_flow.ensure_codex_mcp_registered",
        lambda **kwargs: "registered",
    )
    monkeypatch.setattr(
        "hermit_agent.install_flow.remove_codex_reply_hook",
        lambda **kwargs: "removed",
    )

    summary = run_install(cwd=str(tmp_path), assume_yes=True)

    assert summary.gateway_api_key_created is True
    assert summary.model_selection_status == "auto (gpt-5.4, glm-5.1, qwen3-coder:30b)"
    assert summary.gateway_status == "healthy"
    assert summary.mcp_registration_status == "registered"
    assert summary.codex_install_status == "installed"
    assert summary.codex_marketplace_status == "registered"
    assert summary.codex_reply_hook_status == "removed"
    assert summary.codex_runtime_version == "0.1.31"
    assert any("runtime dir: /tmp/runtime" == item for item in summary.codex_details)
    assert any("codex mcp registration: registered" == item for item in summary.codex_details)


def test_run_startup_self_heal_repairs_common_local_state(tmp_path, monkeypatch):
    global_settings = tmp_path / "global-settings.json"
    monkeypatch.setattr("hermit_agent.install_flow.GLOBAL_SETTINGS_PATH", global_settings)
    monkeypatch.setattr("hermit_agent.config.GLOBAL_SETTINGS_PATH", global_settings)
    monkeypatch.setattr("hermit_agent.install_flow.ensure_gateway_api_key", lambda *, settings_path: (True, "hermit-mcp-test"))
    monkeypatch.setattr("hermit_agent.install_flow.ensure_gateway_running", lambda *, cwd: "started")
    monkeypatch.setattr("hermit_agent.install_flow.inspect_claude_mcp_registration", lambda **kwargs: "missing")
    monkeypatch.setattr("hermit_agent.install_flow.get_codex_runtime_version", lambda *, cwd: None)

    summary = run_startup_self_heal(cwd=str(tmp_path))

    assert summary.settings_initialized is True
    assert summary.gateway_api_key_created is True
    assert summary.gateway_status == "started"
    assert summary.mcp_registration_status == "missing"
    assert summary.codex_runtime_status == "missing"


def test_run_install_surfaces_gateway_failure_in_next_steps(tmp_path, monkeypatch):
    global_settings = tmp_path / "global-settings.json"
    global_settings.write_text(json.dumps({"gateway_api_key": ""}), encoding="utf-8")
    monkeypatch.setattr("hermit_agent.config.GLOBAL_SETTINGS_PATH", global_settings)
    monkeypatch.setattr("hermit_agent.install_flow._prompt_yes_no", lambda *args, **kwargs: False)
    monkeypatch.setattr("hermit_agent.install_flow.configure_model_preferences", lambda **kwargs: "auto (gpt-5.4, glm-5.1, qwen3-coder:30b)")
    monkeypatch.setattr("hermit_agent.install_flow.ensure_gateway_running", lambda *, cwd: "start-failed")

    summary = run_install(cwd=str(tmp_path), assume_yes=False, skip_mcp_register=True, skip_codex=True)

    assert summary.gateway_status == "start-failed"
    assert any("gateway" in step.lower() for step in summary.next_steps)


def test_configure_model_preferences_can_set_auto_mode_and_priority_order(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"model": "gpt-5.4"}), encoding="utf-8")
    monkeypatch.setattr("hermit_agent.install_flow._stdin_interactive", lambda: True)
    answers = iter(["", "2"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    status = configure_model_preferences(settings_path=settings_path, assume_yes=False)

    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert status == "auto (glm-5.1, gpt-5.4, qwen3-coder:30b)"
    assert saved["model"] == "__auto__"
    assert saved["routing"]["priority_models"][0]["model"] == "glm-5.1"


def test_configure_model_preferences_can_set_fixed_model(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr("hermit_agent.install_flow._stdin_interactive", lambda: True)
    answers = iter(["2", "", "3"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    status = configure_model_preferences(settings_path=settings_path, assume_yes=False)

    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert status == "fixed (qwen3-coder:30b)"
    assert saved["model"] == "qwen3-coder:30b"
    assert saved["routing"]["priority_models"][0]["model"] == "gpt-5.4"
