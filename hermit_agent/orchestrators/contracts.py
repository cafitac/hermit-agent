"""Orchestrator-neutral contracts for Hermit executor integrations.

These DTOs define the shared language between Hermit core and higher-level
orchestrators such as Claude Code, Codex, and Hermes Agent. The first slice is
intentionally behavior-free: existing adapters can migrate toward these shapes
without changing runtime routing in the same PR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class TaskEventKind(str, Enum):
    """Lifecycle event kinds emitted from Hermit back to an orchestrator."""

    SUBMITTED = "submitted"
    PROGRESS = "progress"
    WAITING = "waiting"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


class AdapterHealthStatus(str, Enum):
    """Health status for an optional orchestrator integration."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class AdapterInstallStatus(str, Enum):
    """Install/setup result for an orchestrator adapter."""

    PRINTED = "printed"
    REGISTERED = "registered"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class TaskRequest:
    """Orchestrator-neutral request to run a Hermit executor task."""

    task: str
    cwd: str
    model: str | None = None
    max_turns: int | None = None
    user: str | None = None
    parent_session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskHandle:
    """Stable handle returned after an orchestrator submits a task."""

    task_id: str
    status: str
    url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskEvent:
    """Task lifecycle event that adapters can map to their native UI/channel."""

    task_id: str
    kind: TaskEventKind
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InteractivePrompt:
    """Prompt emitted when Hermit needs orchestrator/user input."""

    task_id: str
    question: str
    options: tuple[str, ...] = ()
    prompt_kind: str = "waiting"
    tool_name: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptReply:
    """Reply payload returned by an orchestrator for a waiting prompt."""

    task_id: str
    answer: str
    approved: bool | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterHealth:
    """Read-only adapter health/check result."""

    name: str
    status: AdapterHealthStatus
    message: str = ""
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdapterInstallResult:
    """Result of printing, checking, or applying adapter setup instructions."""

    name: str
    status: AdapterInstallStatus
    message: str = ""
    details: tuple[str, ...] = ()
    changed: bool = False


@runtime_checkable
class OrchestratorAdapter(Protocol):
    """Minimal lifecycle contract for higher-level Hermit orchestrators."""

    name: str

    def install_or_print_instructions(self, *, cwd: str, fix: bool) -> AdapterInstallResult:
        """Return setup instructions or apply an explicit adapter registration fix."""

    def health(self, *, cwd: str) -> AdapterHealth:
        """Return read-only adapter health for diagnostics/doctor output."""

    def submit_task(self, request: TaskRequest) -> TaskHandle:
        """Submit a task to Hermit and return a stable task handle."""

    def emit_event(self, task_id: str, event: TaskEvent) -> None:
        """Deliver a Hermit lifecycle event to the orchestrator surface."""

    def wait_for_reply(self, task_id: str, prompt: InteractivePrompt) -> PromptReply | None:
        """Wait for or fetch an orchestrator reply to a Hermit interactive prompt."""

    def cancel(self, task_id: str) -> None:
        """Cancel an in-flight task or clear adapter-side task state."""
