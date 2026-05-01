from __future__ import annotations

import pytest

from hermit_agent.orchestrators import (
    AdapterHealthStatus,
    AdapterInstallStatus,
    ClaudeCodeMcpAdapter,
    InteractivePrompt,
    TaskEvent,
    TaskEventKind,
    TaskRequest,
)


def test_claude_adapter_print_only_returns_instructions_without_registering(monkeypatch):
    calls: list[object] = []

    def fail_register(**kwargs):
        calls.append(kwargs)
        raise AssertionError("print-only path must not register Claude MCP")

    monkeypatch.setattr("hermit_agent.orchestrators.claude.register_claude_mcp", fail_register)

    result = ClaudeCodeMcpAdapter().install_or_print_instructions(cwd="/repo", fix=False)

    assert result.name == "claude-code"
    assert result.status == AdapterInstallStatus.PRINTED
    assert result.changed is False
    assert any("hermit-channel" in detail for detail in result.details)
    assert any("hermit mcp-server" in detail for detail in result.details)
    assert calls == []


def test_claude_adapter_fix_maps_registration_statuses(monkeypatch):
    monkeypatch.setattr(
        "hermit_agent.orchestrators.claude.register_claude_mcp",
        lambda **kwargs: ("registered", "/tmp/.claude.json", "/tmp/.claude.json.backup"),
    )

    registered = ClaudeCodeMcpAdapter().install_or_print_instructions(cwd="/repo", fix=True)

    assert registered.status == AdapterInstallStatus.REGISTERED
    assert registered.changed is True
    assert registered.details == ("path: /tmp/.claude.json", "backup: /tmp/.claude.json.backup")

    monkeypatch.setattr(
        "hermit_agent.orchestrators.claude.register_claude_mcp",
        lambda **kwargs: ("unchanged", "/tmp/.claude.json", None),
    )

    unchanged = ClaudeCodeMcpAdapter().install_or_print_instructions(cwd="/repo", fix=True)

    assert unchanged.status == AdapterInstallStatus.UNCHANGED
    assert unchanged.changed is False
    assert unchanged.details == ("path: /tmp/.claude.json",)


def test_claude_adapter_health_maps_registration_status(monkeypatch):
    monkeypatch.setattr("hermit_agent.orchestrators.claude.inspect_claude_mcp_registration", lambda **kwargs: "registered")
    assert ClaudeCodeMcpAdapter().health(cwd="/repo").status == AdapterHealthStatus.PASS

    monkeypatch.setattr("hermit_agent.orchestrators.claude.inspect_claude_mcp_registration", lambda **kwargs: "missing")
    missing = ClaudeCodeMcpAdapter().health(cwd="/repo")
    assert missing.status == AdapterHealthStatus.WARN
    assert "missing" in missing.message

    monkeypatch.setattr("hermit_agent.orchestrators.claude.inspect_claude_mcp_registration", lambda **kwargs: "invalid")
    invalid = ClaudeCodeMcpAdapter().health(cwd="/repo")
    assert invalid.status == AdapterHealthStatus.FAIL
    assert "invalid" in invalid.message


def test_claude_adapter_lifecycle_methods_are_explicitly_unsupported():
    adapter = ClaudeCodeMcpAdapter()

    with pytest.raises(NotImplementedError, match="MCP server path"):
        adapter.submit_task(TaskRequest(task="do it", cwd="/repo"))
    with pytest.raises(NotImplementedError, match="MCP server path"):
        adapter.emit_event("task-1", TaskEvent(task_id="task-1", kind=TaskEventKind.RUNNING))
    with pytest.raises(NotImplementedError, match="MCP server path"):
        adapter.wait_for_reply("task-1", InteractivePrompt(task_id="task-1", question="Continue?"))
    with pytest.raises(NotImplementedError, match="MCP server path"):
        adapter.cancel("task-1")
