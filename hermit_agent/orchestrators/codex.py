"""Codex adapter wrappers around existing install helpers.

This module maps Codex integration setup/health helpers into the neutral adapter
DTO layer without changing codex-channels, MCP, or runtime delivery behavior.
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
from ..install_flow import (
    ensure_codex_channels_ready,
    ensure_codex_marketplace_registered,
    ensure_codex_mcp_registered,
    get_codex_runtime_version,
    remove_codex_reply_hook,
)


class CodexAdapter:
    """Adapter DTO wrapper for Hermit's Codex integration setup surface."""

    name = "codex"

    def __init__(self, *, codex_command: str = "codex", scope: str = "user") -> None:
        self.codex_command = codex_command
        self.scope = scope

    def install_or_print_instructions(self, *, cwd: str, fix: bool) -> AdapterInstallResult:
        if not fix:
            return AdapterInstallResult(
                name=self.name,
                status=AdapterInstallStatus.SKIPPED,
                message="Codex setup not changed from print-only adapter path",
                details=(
                    "Use fix=True to install/refresh codex-channels and Codex MCP registration.",
                    "Existing setup path registers Codex marketplace and codex mcp hermit-channel.",
                ),
                changed=False,
            )

        try:
            runtime_status, runtime_details, runtime_version = ensure_codex_channels_ready(
                cwd=cwd,
                codex_command=self.codex_command,
                scope=self.scope,
            )
            marketplace_status = ensure_codex_marketplace_registered(
                cwd=cwd,
                codex_command=self.codex_command,
                scope=self.scope,
            )
            mcp_status = ensure_codex_mcp_registered(cwd=cwd, codex_command=self.codex_command)
            hook_status = remove_codex_reply_hook(cwd=cwd)
        except Exception as exc:
            return AdapterInstallResult(
                name=self.name,
                status=AdapterInstallStatus.FAILED,
                message=f"failed ({exc})",
                changed=False,
            )

        details: list[str] = []
        if runtime_version:
            details.append(f"runtime version: {runtime_version}")
        details.extend(
            [
                f"marketplace: {marketplace_status}",
                f"mcp registration: {mcp_status}",
                f"legacy reply hook: {hook_status}",
            ]
        )
        details.extend(runtime_details)
        return AdapterInstallResult(
            name=self.name,
            status=_install_status_from_codex_statuses(runtime_status, marketplace_status, mcp_status, hook_status),
            message=runtime_status,
            details=tuple(details),
            changed=_codex_statuses_changed(runtime_status, marketplace_status, mcp_status, hook_status),
        )

    def health(self, *, cwd: str) -> AdapterHealth:
        version = get_codex_runtime_version(cwd=cwd)
        if version:
            return AdapterHealth(
                name=self.name,
                status=AdapterHealthStatus.PASS,
                message="codex-channels runtime installed",
                details=(f"runtime version: {version}",),
            )
        return AdapterHealth(
            name=self.name,
            status=AdapterHealthStatus.WARN,
            message="codex-channels runtime missing — run `hermit install` or use fix=True adapter setup",
        )

    def submit_task(self, request: TaskRequest) -> TaskHandle:
        raise NotImplementedError("Codex task submission still uses the existing Codex channel/MCP runtime paths")

    def emit_event(self, task_id: str, event: TaskEvent) -> None:
        raise NotImplementedError("Codex event delivery still uses the existing Codex channel/MCP runtime paths")

    def wait_for_reply(self, task_id: str, prompt: InteractivePrompt) -> PromptReply | None:
        raise NotImplementedError("Codex reply delivery still uses the existing Codex channel/MCP runtime paths")

    def cancel(self, task_id: str) -> None:
        raise NotImplementedError("Codex cancellation still uses the existing Codex channel/MCP runtime paths")


def _codex_statuses_changed(runtime_status: str, marketplace_status: str, mcp_status: str, hook_status: str) -> bool:
    return any(
        status in {"installed", "registered", "removed"}
        for status in (runtime_status, marketplace_status, mcp_status, hook_status)
    )


def _install_status_from_codex_statuses(
    runtime_status: str,
    marketplace_status: str,
    mcp_status: str,
    hook_status: str,
) -> AdapterInstallStatus:
    if any(status.startswith("failed") for status in (runtime_status, marketplace_status, mcp_status, hook_status)):
        return AdapterInstallStatus.FAILED
    if _codex_statuses_changed(runtime_status, marketplace_status, mcp_status, hook_status):
        return AdapterInstallStatus.REGISTERED
    return AdapterInstallStatus.UNCHANGED
