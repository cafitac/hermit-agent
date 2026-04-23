from __future__ import annotations

from hermit_agent.doctor import format_doctor_fix_summary
from hermit_agent.install_flow import InstallSummary, StartupHealSummary


def test_format_doctor_fix_summary_includes_repair_status(monkeypatch):
    monkeypatch.setattr(
        "hermit_agent.doctor.run_startup_self_heal",
        lambda **kwargs: StartupHealSummary(
            settings_initialized=True,
            gateway_api_key_created=True,
            gateway_status="started",
            mcp_registration_status="missing",
            codex_runtime_status="missing",
        ),
    )
    monkeypatch.setattr(
        "hermit_agent.doctor.run_install",
        lambda **kwargs: InstallSummary(
            settings_path="/tmp/settings.json",
            gateway_api_key_created=True,
            gateway_api_key_present=True,
            gateway_status="healthy",
            mcp_registration_status="registered",
            codex_install_status="installed",
            codex_runtime_version="0.1.28",
            next_steps=["Run Hermit."],
        ),
    )

    text = format_doctor_fix_summary(cwd="/tmp/demo")

    assert "Hermit doctor --fix complete." in text
    assert "gateway=started" in text
    assert "mcp=registered" in text
    assert "codex=installed" in text
    assert "codex-facing surface remains: hermit-channel MCP" in text
    assert "codex integration runtime version: 0.1.28" in text
