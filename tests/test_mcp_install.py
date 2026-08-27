from __future__ import annotations

from pathlib import Path

from hermit_agent.executor_readiness import ExecutorReadiness


def test_install_claude_registers_only_claude_mcp(monkeypatch, tmp_path) -> None:
    from hermit_agent import mcp_install

    calls: list[object] = []
    monkeypatch.setattr(mcp_install, "init_settings_file", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(mcp_install, "ensure_gateway_api_key", lambda **kwargs: calls.append(("key", kwargs)) or (True, "key"))
    monkeypatch.setattr(mcp_install, "ensure_gateway_running", lambda **kwargs: calls.append(("gateway", kwargs)) or "started")
    monkeypatch.setattr(mcp_install, "inspect_executor_readiness", lambda _cfg: ExecutorReadiness("ready", (), ()))
    monkeypatch.setattr(mcp_install, "register_claude_mcp", lambda **kwargs: calls.append(("claude", kwargs)) or "registered")
    monkeypatch.setattr(mcp_install, "ensure_codex_mcp_registered", lambda **kwargs: (_ for _ in ()).throw(AssertionError("Codex must not be called")))

    summary = mcp_install.install_mcp_host(target="claude", cwd=str(tmp_path))

    assert summary.claude_status == "registered"
    assert summary.codex_status == "skipped"
    assert [name for name, _kwargs in calls] == ["key", "gateway", "claude"]


def test_install_codex_registers_only_codex_mcp(monkeypatch, tmp_path) -> None:
    from hermit_agent import mcp_install

    monkeypatch.setattr(mcp_install, "init_settings_file", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(mcp_install, "ensure_gateway_api_key", lambda **kwargs: (True, "key"))
    monkeypatch.setattr(mcp_install, "ensure_gateway_running", lambda **kwargs: "started")
    monkeypatch.setattr(mcp_install, "inspect_executor_readiness", lambda _cfg: ExecutorReadiness("ready", (), ()))
    monkeypatch.setattr(mcp_install, "register_claude_mcp", lambda **kwargs: (_ for _ in ()).throw(AssertionError("Claude must not be called")))
    calls: list[dict[str, str]] = []
    monkeypatch.setattr(mcp_install, "ensure_codex_mcp_registered", lambda **kwargs: calls.append(kwargs) or "registered")

    summary = mcp_install.install_mcp_host(target="codex", cwd=str(tmp_path), codex_command="codex-beta")

    assert summary.claude_status == "skipped"
    assert summary.codex_status == "registered"
    assert calls == [{"codex_command": "codex-beta"}]


def test_install_summary_tells_user_to_restart_host() -> None:
    from hermit_agent.mcp_install import MCPInstallSummary, format_install_summary

    text = format_install_summary(
        MCPInstallSummary(
            target="codex",
            settings_path="/tmp/settings.json",
            gateway_status="healthy",
            codex_status="registered",
        )
    )

    assert "Codex MCP: registered" in text
    assert "Restart the selected host" in text


def test_install_summary_does_not_claim_success_without_an_executor() -> None:
    from hermit_agent.mcp_install import MCPInstallSummary, format_install_summary

    summary = MCPInstallSummary(
        target="codex",
        settings_path="/tmp/settings.json",
        gateway_status="healthy",
        codex_status="registered",
        executor=ExecutorReadiness("needs-configuration", ("Ollama model missing: qwen3-coder:30b",), ("Run `ollama pull qwen3-coder:30b`.",)),
    )

    assert not summary.succeeded
    text = format_install_summary(summary)
    assert "installation needs attention" in text.lower()
    assert "will not accept work" in text


def test_register_claude_uses_user_scoped_cli_registration(monkeypatch) -> None:
    from hermit_agent import mcp_install

    calls: list[list[str]] = []

    class Result:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def run(command: list[str], **_kwargs) -> Result:
        calls.append(command)
        return Result(1) if command[2] == "get" else Result(0)

    monkeypatch.setattr(mcp_install.subprocess, "run", run)

    assert mcp_install.register_claude_mcp() == "registered"
    assert calls == [
        ["claude", "mcp", "get", "hermit"],
        ["claude", "mcp", "add", "hermit", "--scope", "user", "--", "hermit", "mcp-server"],
    ]


def test_doctor_reports_missing_host_registration(monkeypatch, tmp_path) -> None:
    from hermit_agent import mcp_install

    monkeypatch.setattr(mcp_install, "inspect_claude_mcp_registration", lambda **kwargs: "missing")
    monkeypatch.setattr(mcp_install, "probe_gateway_health", lambda **kwargs: False)
    monkeypatch.setattr(mcp_install, "inspect_executor_readiness", lambda _cfg: ExecutorReadiness("needs-configuration", (), ()))
    monkeypatch.setattr(mcp_install.Path, "home", lambda: tmp_path)

    class Result:
        returncode = 1

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Result())

    summary = mcp_install.inspect_mcp_install(cwd=str(tmp_path))

    assert summary.gateway_status == "not-running"
    assert summary.claude_status == "missing"
    assert summary.codex_status == "missing"


def test_doctor_text_summary_redacts_diagnostic_credentials() -> None:
    from hermit_agent.mcp_install import MCPInstallSummary, format_doctor_summary

    text = format_doctor_summary(
        MCPInstallSummary(
            target="all",
            settings_path="/tmp/settings.json",
            gateway_status="failed (gateway_api_key=hermit-mcp-abcdef0123456789)",
            claude_status="failed (Bearer gho_very-secret-token)",
            codex_status="failed (https://user:password@example.com?api_key=super-secret)",
            executor=ExecutorReadiness("needs-configuration", ("pypi-very-secret-token",), ()),
        )
    )

    assert "[REDACTED]" in text
    for secret in ("abcdef0123456789", "gho_very-secret-token", "user:password", "super-secret", "pypi-very-secret-token"):
        assert secret not in text


def test_gateway_port_conflict_moves_hermit_without_touching_the_other_process(monkeypatch, tmp_path) -> None:
    from hermit_agent import mcp_install

    spawned: list[dict] = []
    responses = iter([False, True])
    monkeypatch.setattr(mcp_install, "probe_gateway_health", lambda **kwargs: next(responses))
    monkeypatch.setattr(mcp_install, "_is_port_available", lambda host, port: False)
    monkeypatch.setattr(mcp_install, "_find_available_port", lambda host: 41876)
    monkeypatch.setattr(mcp_install.shutil, "which", lambda name: "/tmp/hermit-gateway")
    monkeypatch.setattr(mcp_install.subprocess, "Popen", lambda *args, **kwargs: spawned.append(kwargs))
    settings = tmp_path / "settings.json"
    settings.write_text("{}")

    status = mcp_install.ensure_gateway_running(settings_path=settings, gateway_url="http://127.0.0.1:8765")

    assert status == "started"
    assert '"gateway_url": "http://127.0.0.1:41876"' in settings.read_text()
    assert spawned[0]["env"]["HERMIT_GATEWAY_PORT"] == "41876"


def test_gateway_restarts_when_its_configured_port_is_free(monkeypatch, tmp_path) -> None:
    from hermit_agent import mcp_install

    spawned: list[dict] = []
    responses = iter([False, True])
    monkeypatch.setattr(mcp_install, "probe_gateway_health", lambda **kwargs: next(responses))
    monkeypatch.setattr(mcp_install, "_is_port_available", lambda host, port: True)
    monkeypatch.setattr(mcp_install.shutil, "which", lambda name: "/tmp/hermit-gateway")
    monkeypatch.setattr(mcp_install.subprocess, "Popen", lambda *args, **kwargs: spawned.append(kwargs))

    assert mcp_install.ensure_gateway_running(settings_path=tmp_path / "settings.json", gateway_url="http://127.0.0.1:8765") == "started"
    assert spawned[0]["env"]["HERMIT_GATEWAY_PORT"] == "8765"
