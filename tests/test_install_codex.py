from __future__ import annotations


def test_run_install_codex_reports_marketplace_registration(monkeypatch):
    from hermit_agent.install_codex import run_install_codex

    class DummyReport:
        install_mode = "package"
        source_path = None
        runtime_dir = "/tmp/runtime"
        settings_path = "/tmp/settings.json"
        marketplace_path = "/tmp/.agents/plugins/marketplace.json"
        state_file = "/tmp/.codex-channels/state.json"

    monkeypatch.setattr("hermit_agent.install_codex.install_codex_channels", lambda **kwargs: DummyReport())
    monkeypatch.setattr("hermit_agent.install_codex.ensure_codex_marketplace_registered", lambda **kwargs: "registered")
    monkeypatch.setattr("hermit_agent.install_codex.ensure_codex_mcp_registered", lambda **kwargs: "registered")
    monkeypatch.setattr("hermit_agent.install_codex.remove_codex_reply_hook", lambda **kwargs: "removed")

    text = run_install_codex(cwd="/tmp/demo", codex_command="codex", scope="workspace")

    assert "Hermit Codex integration is ready." in text
    assert "- Codex marketplace registration: registered" in text
    assert "- Codex MCP registration: registered" in text
    assert "- legacy Codex reply hook: removed" in text
