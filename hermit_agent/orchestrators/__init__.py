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
from .events import (
    channel_action_to_task_event,
    sse_event_to_task_event,
    task_status_payload_to_task_event,
)
from .hermes import HermesMcpAdapter
from .prompts import (
    adapter_prompt_to_runtime_prompt,
    prompt_reply_from_answer,
    runtime_prompt_to_adapter_prompt,
)

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
    "adapter_prompt_to_runtime_prompt",
    "channel_action_to_task_event",
    "prompt_reply_from_answer",
    "runtime_prompt_to_adapter_prompt",
    "sse_event_to_task_event",
    "task_status_payload_to_task_event",
]
