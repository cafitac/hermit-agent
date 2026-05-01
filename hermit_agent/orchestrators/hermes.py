"""Hermes Agent adapter wrappers around existing install/doctor helpers.

This module is intentionally thin: it maps the existing Hermes MCP setup and
smoke-check helpers into the orchestrator-neutral DTOs without rewiring CLI or
runtime behavior yet.
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
from ..doctor import DiagCheck, DiagStatus, _check_hermes_mcp as check_hermes_mcp
from ..install_flow import (
    ensure_hermes_mcp_registered,
    format_hermes_mcp_config_snippet,
    run_hermes_mcp_connection_test,
)


class HermesMcpAdapter:
    """Adapter DTO wrapper for Hermes Agent's Hermit MCP integration."""

    name = "hermes"

    def install_or_print_instructions(self, *, cwd: str, fix: bool) -> AdapterInstallResult:
        if not fix:
            snippet = format_hermes_mcp_config_snippet(cwd=cwd)
            return AdapterInstallResult(
                name=self.name,
                status=AdapterInstallStatus.PRINTED,
                message="print-only Hermes MCP registration instructions",
                details=tuple(line for line in snippet.splitlines() if line.strip()),
                changed=False,
            )

        status = ensure_hermes_mcp_registered(cwd=cwd)
        return _install_result_from_status(status)

    def health(self, *, cwd: str) -> AdapterHealth:
        return _health_from_diag_check(check_hermes_mcp(cwd))

    def live_smoke(self, *, cwd: str) -> AdapterHealth:
        status = run_hermes_mcp_connection_test(cwd=cwd)
        if status == "passed":
            health_status = AdapterHealthStatus.PASS
        elif status == "missing-hermes-cli":
            health_status = AdapterHealthStatus.WARN
        else:
            health_status = AdapterHealthStatus.FAIL
        return AdapterHealth(name=self.name, status=health_status, message=status)

    def submit_task(self, request: TaskRequest) -> TaskHandle:
        raise NotImplementedError("Hermes task submission still uses the MCP server path directly")

    def emit_event(self, task_id: str, event: TaskEvent) -> None:
        raise NotImplementedError("Hermes event delivery still uses the MCP server path directly")

    def wait_for_reply(self, task_id: str, prompt: InteractivePrompt) -> PromptReply | None:
        raise NotImplementedError("Hermes reply delivery still uses the MCP server path directly")

    def cancel(self, task_id: str) -> None:
        raise NotImplementedError("Hermes cancellation still uses the MCP server path directly")


def _install_result_from_status(status: str) -> AdapterInstallResult:
    if status == "registered":
        install_status = AdapterInstallStatus.REGISTERED
        changed = True
    elif status == "unchanged":
        install_status = AdapterInstallStatus.UNCHANGED
        changed = False
    else:
        install_status = AdapterInstallStatus.FAILED
        changed = False
    return AdapterInstallResult(
        name=HermesMcpAdapter.name,
        status=install_status,
        message=status,
        changed=changed,
    )


def _health_from_diag_check(check: DiagCheck) -> AdapterHealth:
    status = _health_status_from_diag_status(check.status)
    return AdapterHealth(name=HermesMcpAdapter.name, status=status, message=check.message)


def _health_status_from_diag_status(status: DiagStatus) -> AdapterHealthStatus:
    if status == DiagStatus.PASS:
        return AdapterHealthStatus.PASS
    if status == DiagStatus.FAIL:
        return AdapterHealthStatus.FAIL
    return AdapterHealthStatus.WARN
