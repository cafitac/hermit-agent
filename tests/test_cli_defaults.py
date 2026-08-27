from __future__ import annotations

import json

import pytest


def test_cli_help_is_mcp_only() -> None:
    from hermit_agent.__main__ import _build_parser

    help_text = _build_parser().format_help()

    assert "install" in help_text
    assert "mcp-server" in help_text
    assert "Interactive TUI" not in help_text
    assert "status" not in help_text
    assert "pending" not in help_text


def test_cli_install_accepts_claude_target(monkeypatch, capsys) -> None:
    from hermit_agent import __main__ as main_mod
    from hermit_agent.mcp_install import MCPInstallSummary

    calls: list[dict[str, str]] = []
    monkeypatch.setattr(
        main_mod,
        "install_mcp_host",
        lambda **kwargs: calls.append(kwargs)
        or MCPInstallSummary(
            target="claude",
            settings_path="/tmp/settings.json",
            gateway_status="started",
            claude_status="registered",
        ),
    )

    with pytest.raises(SystemExit) as exc:
        main_mod.main(["install", "claude", "--cwd", "/tmp/workspace"])

    assert exc.value.code == 0
    assert calls == [{"target": "claude", "cwd": "/tmp/workspace", "claude_command": "claude", "codex_command": "codex"}]
    assert "Claude Code MCP: registered" in capsys.readouterr().out


def test_cli_install_failure_returns_nonzero(monkeypatch) -> None:
    from hermit_agent import __main__ as main_mod
    from hermit_agent.mcp_install import MCPInstallSummary

    monkeypatch.setattr(
        main_mod,
        "install_mcp_host",
        lambda **kwargs: MCPInstallSummary(
            target="codex",
            settings_path="/tmp/settings.json",
            gateway_status="started",
            codex_status="failed (codex unavailable)",
        ),
    )

    with pytest.raises(SystemExit) as exc:
        main_mod.main(["install", "codex"])

    assert exc.value.code == 1


def test_cli_doctor_is_read_only(monkeypatch, capsys) -> None:
    from hermit_agent import __main__ as main_mod
    from hermit_agent.mcp_install import MCPInstallSummary

    calls: list[dict[str, str]] = []
    monkeypatch.setattr(
        main_mod,
        "inspect_mcp_install",
        lambda **kwargs: calls.append(kwargs)
        or MCPInstallSummary(
            target="all",
            settings_path="/tmp/settings.json",
            gateway_status="healthy",
            claude_status="registered",
            codex_status="registered",
        ),
    )

    with pytest.raises(SystemExit) as exc:
        main_mod.main(["doctor", "--cwd", "/tmp/workspace"])

    assert exc.value.code == 0
    assert calls == [{"cwd": "/tmp/workspace", "claude_command": "claude", "codex_command": "codex"}]
    assert "Hermit MCP readiness" in capsys.readouterr().out


def test_cli_doctor_json_is_machine_readable_and_paste_safe(monkeypatch, capsys) -> None:
    from hermit_agent import __main__ as main_mod
    from hermit_agent.executor_readiness import ExecutorReadiness
    from hermit_agent.mcp_install import MCPInstallSummary

    monkeypatch.setattr(
        main_mod,
        "inspect_mcp_install",
        lambda **_kwargs: MCPInstallSummary(
            target="all",
            settings_path="/tmp/settings.json",
            gateway_status="failed (Bearer super-secret-token)",
            claude_status="registered",
            codex_status="failed (https://alice:password@example.com)",
            executor=ExecutorReadiness("needs-configuration", ("token=top-secret",), ("Run `ollama pull qwen3-coder:30b`.",)),
        ),
    )

    with pytest.raises(SystemExit) as exc:
        main_mod.main(["doctor", "--json"])

    report = json.loads(capsys.readouterr().out)
    assert exc.value.code == 1
    assert report["schema_version"] == 1
    assert report["hosts"] == {"claude_code": "registered", "codex": "failed (https://[REDACTED]@example.com)"}
    assert report["gateway"] == {"status": "failed (Bearer [REDACTED])"}
    assert report["executor"]["details"] == ["token=[REDACTED]"]
    assert "super-secret-token" not in json.dumps(report)
    assert "top-secret" not in json.dumps(report)


def test_cli_starts_mcp_server(monkeypatch) -> None:
    from hermit_agent import __main__ as main_mod

    calls: list[str] = []
    monkeypatch.setattr("hermit_agent.mcp_launcher.main", lambda: calls.append("started"))

    main_mod.main(["mcp-server"])

    assert calls == ["started"]


def test_cli_configure_never_accepts_or_prints_an_api_key(monkeypatch, capsys) -> None:
    from hermit_agent import __main__ as main_mod

    calls: list[dict[str, str]] = []
    monkeypatch.setattr(main_mod, "configure_openai_compatible_provider", lambda **kwargs: calls.append(kwargs) or "/tmp/settings.json")

    main_mod.main(
        [
            "configure",
            "--model",
            "coder-small",
            "--base-url",
            "https://llm.example.com/v1",
            "--api-key-env",
            "BUDGET_KEY",
        ]
    )

    assert calls == [{"model": "coder-small", "base_url": "https://llm.example.com/v1", "api_key_env": "BUDGET_KEY", "provider_name": "openai-compatible"}]
    output = capsys.readouterr().out
    assert "$BUDGET_KEY" in output
    assert "--api-key" not in output
