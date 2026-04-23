from __future__ import annotations


def test_run_install_claude_formats_install_summary_with_codex_skipped(monkeypatch):
    from hermit_agent.install_claude import run_install_claude
    from hermit_agent.install_flow import InstallSummary

    monkeypatch.setattr(
        "hermit_agent.install_claude.run_install",
        lambda **kwargs: InstallSummary(
            settings_path="/tmp/settings.json",
            gateway_api_key_created=True,
            gateway_api_key_present=True,
            gateway_status="healthy",
            mcp_registration_status="registered",
            codex_install_status="skipped",
        ),
    )

    text = run_install_claude(cwd="/tmp/demo", assume_yes=True, skip_mcp_register=False)

    assert "Hermit install is ready." in text
    assert "- MCP registration: registered" in text
    assert "- Codex integration: skipped" in text
