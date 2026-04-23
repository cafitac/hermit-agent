from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .codex_channels_adapter import build_interaction


@dataclass(frozen=True)
class InteractivePrompt:
    task_id: str
    question: str
    options: tuple[str, ...] = ()
    prompt_kind: str = "waiting"
    tool_name: str = ""
    method: str | None = None
    request_id: str | int | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    params: dict[str, Any] | None = None


def default_tool_name(*, prompt_kind: str, method: str | None = None) -> str:
    if method == "item/commandExecution/requestApproval":
        return "bash"
    if method == "item/permissions/requestApproval":
        return "bash"
    if prompt_kind == "permission_ask":
        return "bash"
    return "ask"


def create_interactive_prompt(
    *,
    task_id: str,
    question: str,
    options: list[str] | tuple[str, ...],
    prompt_kind: str = "waiting",
    tool_name: str = "",
    method: str | None = None,
    request_id: str | int | None = None,
    thread_id: str | None = None,
    turn_id: str | None = None,
    params: dict[str, Any] | None = None,
) -> InteractivePrompt:
    resolved_tool_name = tool_name or default_tool_name(prompt_kind=prompt_kind, method=method)
    return InteractivePrompt(
        task_id=task_id,
        question=question,
        options=tuple(options or ()),
        prompt_kind=prompt_kind or "waiting",
        tool_name=resolved_tool_name,
        method=method,
        request_id=request_id,
        thread_id=thread_id,
        turn_id=turn_id,
        params=dict(params) if params is not None else None,
    )


def waiting_prompt_snapshot(prompt: InteractivePrompt) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "question": prompt.question,
        "options": list(prompt.options),
        "tool_name": prompt.tool_name,
    }
    if prompt.method:
        snapshot["method"] = prompt.method
    return snapshot


def channel_notification_meta(prompt: InteractivePrompt) -> dict[str, str]:
    meta = {"task_id": prompt.task_id, "kind": "waiting"}
    if prompt.options:
        meta["options"] = ",".join(prompt.options)
    if prompt.prompt_kind:
        meta["prompt_kind"] = prompt.prompt_kind
    if prompt.tool_name:
        meta["tool_name"] = prompt.tool_name
    return meta


def codex_channels_interaction_kind(prompt: InteractivePrompt) -> str:
    if prompt.method == "item/permissions/requestApproval":
        return "permissions_request"
    if prompt.method == "mcpServer/elicitation/request":
        return "elicitation_request"
    if prompt.prompt_kind == "permission_ask":
        return "approval_request"
    return "user_input_request"


def build_codex_channels_interaction(prompt: InteractivePrompt) -> dict[str, Any]:
    return build_interaction(
        task_id=prompt.task_id,
        kind=codex_channels_interaction_kind(prompt),
        question=prompt.question,
        options=list(prompt.options),
        method=prompt.method,
        thread_id=prompt.thread_id,
        turn_id=prompt.turn_id,
        request_id=prompt.request_id,
    )


def build_codex_app_server_request(prompt: InteractivePrompt) -> dict[str, Any] | None:
    if not prompt.method or prompt.request_id is None:
        return None

    params = dict(prompt.params or {})
    if prompt.thread_id is not None and "threadId" not in params:
        params["threadId"] = prompt.thread_id
    if prompt.turn_id is not None and "turnId" not in params:
        params["turnId"] = prompt.turn_id

    return {
        "id": prompt.request_id,
        "method": prompt.method,
        "params": params,
    }
