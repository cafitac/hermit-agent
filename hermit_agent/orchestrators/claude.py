"""Claude Code adapter wrappers around existing install helpers.

This module is intentionally thin: it maps Claude MCP setup/health helpers
into orchestrator-neutral DTOs without rewiring the MCP runtime path.
"""

from __future__ import annotations

from .contracts import (
    AdapterHealth,
    AdapterHealthStatus,
    AdapterInstallResult,
    AdapterInstallStatus,
    InteractivePrompt,
    PromptReply,
    TaskEvent,
    TaskHandle,
    TaskRequest,
)
from ..install_flow import inspect_claude_mcp_registration, register_claude_mcp, resolve_hermit_mcp_stdio_entry


class ClaudeCodeMcpAdapter:
    """Adapter DTO wrapper for Claude Code's Hermit MCP integration."""

    name = "claude-code"

    def install_or_print_instructions(self, *, cwd: str, fix: bool) -> AdapterInstallResult:
        entry = resolve_hermit_mcp_stdio_entry(cwd=cwd)
        command = str(entry["command"])
        args = [str(arg) for arg in entry.get("args", [])] if isinstance(entry.get("args"), list) else []
        if not fix:
            details = (
                "print-only Claude Code MCP registration instructions",
                "Add `hermit-channel` under ~/.claude.json mcpServers.",
                f"transport: {command} {' '.join(args)}".strip(),
            )
            return AdapterInstallResult(
                name=self.name,
                status=AdapterInstallStatus.PRINTED,
                message="print-only Claude Code MCP registration instructions",
                details=details,
                changed=False,
            )

        try:
            status, path, backup = register_claude_mcp(entry=entry)
        except Exception as exc:
            return AdapterInstallResult(
                name=self.name,
                status=AdapterInstallStatus.FAILED,
                message=f"failed ({exc})",
                changed=False,
            )
        return _install_result_from_status(status, path=path, backup=backup)

    def health(self, *, cwd: str) -> AdapterHealth:
        status = inspect_claude_mcp_registration(entry=resolve_hermit_mcp_stdio_entry(cwd=cwd))
        return _health_from_registration_status(status)

    def submit_task(self, request: TaskRequest) -> TaskHandle:
        raise NotImplementedError("Claude Code task submission still uses the MCP server path directly")

    def emit_event(self, task_id: str, event: TaskEvent) -> None:
        raise NotImplementedError("Claude Code event delivery still uses the MCP server path directly")

    def wait_for_reply(self, task_id: str, prompt: InteractivePrompt) -> PromptReply | None:
        raise NotImplementedError("Claude Code reply delivery still uses the MCP server path directly")

    def cancel(self, task_id: str) -> None:
        raise NotImplementedError("Claude Code cancellation still uses the MCP server path directly")


def _install_result_from_status(status: str, *, path: object, backup: object | None) -> AdapterInstallResult:
    if status == "registered":
        install_status = AdapterInstallStatus.REGISTERED
        changed = True
    elif status == "unchanged":
        install_status = AdapterInstallStatus.UNCHANGED
        changed = False
    else:
        install_status = AdapterInstallStatus.FAILED
        changed = False
    details = [f"path: {path}"]
    if backup is not None:
        details.append(f"backup: {backup}")
    return AdapterInstallResult(
        name=ClaudeCodeMcpAdapter.name,
        status=install_status,
        message=status,
        details=tuple(details),
        changed=changed,
    )


def _health_from_registration_status(status: str) -> AdapterHealth:
    if status == "registered":
        health_status = AdapterHealthStatus.PASS
        message = "hermit-channel registered for Claude Code"
    elif status == "invalid":
        health_status = AdapterHealthStatus.FAIL
        message = "Claude MCP registration invalid"
    else:
        health_status = AdapterHealthStatus.WARN
        message = f"Claude MCP registration {status}"
    return AdapterHealth(name=ClaudeCodeMcpAdapter.name, status=health_status, message=message)
