"""Mappings between runtime interactive prompts and adapter DTOs."""

from __future__ import annotations

from typing import Any

from ..interactive_prompts import InteractivePrompt as RuntimeInteractivePrompt
from ..interactive_prompts import create_interactive_prompt
from .contracts import InteractivePrompt, PromptReply


def runtime_prompt_to_adapter_prompt(prompt: RuntimeInteractivePrompt) -> InteractivePrompt:
    """Convert the existing runtime prompt shape to an orchestrator-neutral DTO."""

    payload: dict[str, Any] = {}
    if prompt.method is not None:
        payload["method"] = prompt.method
    if prompt.request_id is not None:
        payload["request_id"] = prompt.request_id
    if prompt.thread_id is not None:
        payload["thread_id"] = prompt.thread_id
    if prompt.turn_id is not None:
        payload["turn_id"] = prompt.turn_id
    if prompt.params is not None:
        payload["params"] = dict(prompt.params)

    return InteractivePrompt(
        task_id=prompt.task_id,
        question=prompt.question,
        options=tuple(prompt.options),
        prompt_kind=prompt.prompt_kind,
        tool_name=prompt.tool_name,
        payload=payload,
    )


def adapter_prompt_to_runtime_prompt(prompt: InteractivePrompt) -> RuntimeInteractivePrompt:
    """Convert an orchestrator-neutral prompt DTO back to the current runtime shape."""

    params = prompt.payload.get("params")
    return create_interactive_prompt(
        task_id=prompt.task_id,
        question=prompt.question,
        options=prompt.options,
        prompt_kind=prompt.prompt_kind,
        tool_name=prompt.tool_name,
        method=_optional_str(prompt.payload.get("method")),
        request_id=prompt.payload.get("request_id"),
        thread_id=_optional_str(prompt.payload.get("thread_id")),
        turn_id=_optional_str(prompt.payload.get("turn_id")),
        params=dict(params) if isinstance(params, dict) else None,
    )


def prompt_reply_from_answer(*, task_id: str, answer: str) -> PromptReply:
    """Create a neutral prompt reply while preserving a simple approval hint."""

    normalized = answer.strip().casefold()
    approved: bool | None
    if normalized in {"yes", "y", "approve", "approved", "allow"}:
        approved = True
    elif normalized in {"no", "n", "deny", "denied", "reject", "rejected", "cancel"}:
        approved = False
    else:
        approved = None

    return PromptReply(task_id=task_id, answer=answer, approved=approved)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None
