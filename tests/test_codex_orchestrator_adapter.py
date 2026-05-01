from __future__ import annotations

import pytest

from hermit_agent.orchestrators import (
    AdapterHealthStatus,
    AdapterInstallStatus,
    CodexAdapter,
    InteractivePrompt,
    TaskEvent,
    TaskEventKind,
    TaskRequest,
)


def test_codex_adapter_print_only_returns_actionable_skipped_result_without_installing(monkeypatch):
    calls: list[object] = []

    def fail_install(**kwargs):
        calls.append(kwargs)
        raise AssertionError("print-only path must not install Codex integration")

    monkeypatch.setattr("hermit_agent.orchestrators.codex.ensure_codex_channels_ready", fail_install)

    result = CodexAdapter().install_or_print_instructions(cwd="/repo", fix=False)

    assert result.name == "codex"
    assert result.status == AdapterInstallStatus.SKIPPED
    assert result.changed is False
    assert any("fix=True" in detail for detail in result.details)
    assert any("codex mcp" in detail.casefold() for detail in result.details)
    assert calls == []


def test_codex_adapter_fix_maps_install_and_registration_statuses(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_channels(**kwargs):
        calls.append(("channels", kwargs))
        return "installed", ["runtime dir: /tmp/codex", "settings updated: /tmp/settings.json"], "1.2.3"

    def fake_marketplace(**kwargs):
        calls.append(("marketplace", kwargs))
        return "registered"

    def fake_mcp(**kwargs):
        calls.append(("mcp", kwargs))
        return "unchanged"

    def fake_hook(**kwargs):
        calls.append(("hook", kwargs))
        return "absent"

    monkeypatch.setattr("hermit_agent.orchestrators.codex.ensure_codex_channels_ready", fake_channels)
    monkeypatch.setattr("hermit_agent.orchestrators.codex.ensure_codex_marketplace_registered", fake_marketplace)
    monkeypatch.setattr("hermit_agent.orchestrators.codex.ensure_codex_mcp_registered", fake_mcp)
    monkeypatch.setattr("hermit_agent.orchestrators.codex.remove_codex_reply_hook", fake_hook)

    result = CodexAdapter(codex_command="codex-dev", scope="workspace").install_or_print_instructions(cwd="/repo", fix=True)

    assert result.status == AdapterInstallStatus.REGISTERED
    assert result.changed is True
    assert result.message == "installed"
    assert result.details == (
        "runtime version: 1.2.3",
        "marketplace: registered",
        "mcp registration: unchanged",
        "legacy reply hook: absent",
        "runtime dir: /tmp/codex",
        "settings updated: /tmp/settings.json",
    )
    assert calls[0] == ("channels", {"cwd": "/repo", "codex_command": "codex-dev", "scope": "workspace"})
    assert calls[1] == ("marketplace", {"cwd": "/repo", "codex_command": "codex-dev", "scope": "workspace"})
    assert calls[2] == ("mcp", {"cwd": "/repo", "codex_command": "codex-dev"})
    assert calls[3] == ("hook", {"cwd": "/repo"})


def test_codex_adapter_fix_maps_healthy_runtime_to_unchanged(monkeypatch):
    monkeypatch.setattr(
        "hermit_agent.orchestrators.codex.ensure_codex_channels_ready",
        lambda **kwargs: ("healthy", ["runtime version: 1.2.3"], "1.2.3"),
    )
    monkeypatch.setattr("hermit_agent.orchestrators.codex.ensure_codex_marketplace_registered", lambda **kwargs: "unchanged")
    monkeypatch.setattr("hermit_agent.orchestrators.codex.ensure_codex_mcp_registered", lambda **kwargs: "unchanged")
    monkeypatch.setattr("hermit_agent.orchestrators.codex.remove_codex_reply_hook", lambda **kwargs: "absent")

    result = CodexAdapter().install_or_print_instructions(cwd="/repo", fix=True)

    assert result.status == AdapterInstallStatus.UNCHANGED
    assert result.changed is False


def test_codex_adapter_health_uses_runtime_version(monkeypatch):
    monkeypatch.setattr("hermit_agent.orchestrators.codex.get_codex_runtime_version", lambda **kwargs: "1.2.3")
    healthy = CodexAdapter().health(cwd="/repo")
    assert healthy.status == AdapterHealthStatus.PASS
    assert healthy.message == "codex-channels runtime installed"
    assert healthy.details == ("runtime version: 1.2.3",)

    monkeypatch.setattr("hermit_agent.orchestrators.codex.get_codex_runtime_version", lambda **kwargs: None)
    missing = CodexAdapter().health(cwd="/repo")
    assert missing.status == AdapterHealthStatus.WARN
    assert "missing" in missing.message


def test_codex_adapter_lifecycle_methods_are_explicitly_unsupported():
    adapter = CodexAdapter()

    with pytest.raises(NotImplementedError, match="existing Codex channel"):
        adapter.submit_task(TaskRequest(task="do it", cwd="/repo"))
    with pytest.raises(NotImplementedError, match="existing Codex channel"):
        adapter.emit_event("task-1", TaskEvent(task_id="task-1", kind=TaskEventKind.RUNNING))
    with pytest.raises(NotImplementedError, match="existing Codex channel"):
        adapter.wait_for_reply("task-1", InteractivePrompt(task_id="task-1", question="Continue?"))
    with pytest.raises(NotImplementedError, match="existing Codex channel"):
        adapter.cancel("task-1")
