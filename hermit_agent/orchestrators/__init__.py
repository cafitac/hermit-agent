"""Orchestrator adapter contracts for Hermit executor integrations."""

from .contracts import (
    AdapterHealth,
    AdapterHealthStatus,
    AdapterInstallResult,
    AdapterInstallStatus,
    InteractivePrompt,
    OrchestratorAdapter,
    PromptReply,
    TaskEvent,
    TaskEventKind,
    TaskHandle,
    TaskRequest,
)
from .hermes import HermesMcpAdapter

__all__ = [
    "AdapterHealth",
    "AdapterHealthStatus",
    "AdapterInstallResult",
    "AdapterInstallStatus",
    "HermesMcpAdapter",
    "InteractivePrompt",
    "OrchestratorAdapter",
    "PromptReply",
    "TaskEvent",
    "TaskEventKind",
    "TaskHandle",
    "TaskRequest",
]
