"""Pure mapping helpers for orchestrator-neutral task lifecycle events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import TaskEvent, TaskEventKind


def _copy_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return dict(payload)


def _string_value(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _options_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(str(item) for item in value)
    except TypeError:
        return (str(value),)


def _prompt_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    payload = _copy_payload(event)
    event_type = _string_value(event.get("type") or event.get("kind") or event.get("status"), "waiting")
    payload["prompt_kind"] = event_type
    if "options" in payload:
        payload["options"] = _options_tuple(payload.get("options"))
    if "tool" in payload and "tool_name" not in payload:
        payload["tool_name"] = payload.pop("tool")
    if event_type == "waiting" and "tool_name" not in payload:
        payload["tool_name"] = "ask"
    if event_type == "permission_ask" and "tool_name" not in payload:
        payload["tool_name"] = "bash"
    return payload


def sse_event_to_task_event(task_id: str, event: Mapping[str, Any]) -> TaskEvent | None:
    """Convert a Gateway SSE payload into a neutral TaskEvent.

    This is intentionally pure and side-effect free. It mirrors the existing
    runtime event shapes without changing how MCP/channel delivery works.
    Unknown/non-lifecycle streaming events return None so callers can ignore
    them without inventing misleading lifecycle states.
    """

    event_type = _string_value(event.get("type"))
    payload = _copy_payload(event)

    if event_type in {"submitted"}:
        return TaskEvent(task_id=task_id, kind=TaskEventKind.SUBMITTED, payload=payload)
    if event_type in {"reply_ack", "running"}:
        return TaskEvent(task_id=task_id, kind=TaskEventKind.RUNNING, payload=payload)
    if event_type in {"progress", "status", "tool_use", "tool_result", "model_changed"}:
        return TaskEvent(
            task_id=task_id,
            kind=TaskEventKind.PROGRESS,
            message=_string_value(event.get("message") or event.get("detail") or event.get("content")),
            payload=payload,
        )
    if event_type in {"waiting", "permission_ask"}:
        question = _string_value(event.get("question"))
        return TaskEvent(
            task_id=task_id,
            kind=TaskEventKind.WAITING,
            message=question,
            payload=_prompt_payload(event),
        )
    if event_type == "done":
        result = _string_value(event.get("result"))
        return TaskEvent(task_id=task_id, kind=TaskEventKind.DONE, message=result, payload=payload)
    if event_type == "error":
        message = _string_value(event.get("message"))
        return TaskEvent(task_id=task_id, kind=TaskEventKind.ERROR, message=message, payload=payload)
    if event_type == "cancelled":
        message = _string_value(event.get("message"), "Task cancelled") or "Task cancelled"
        return TaskEvent(task_id=task_id, kind=TaskEventKind.CANCELLED, message=message, payload=payload)
    return None


def channel_action_to_task_event(task_id: str, action: Any) -> TaskEvent | None:
    """Convert an existing ChannelAction-like object into a neutral TaskEvent."""

    action_kind = _string_value(getattr(action, "kind", ""))
    if action_kind == "prompt":
        question = _string_value(getattr(action, "question", ""))
        return TaskEvent(
            task_id=task_id,
            kind=TaskEventKind.WAITING,
            message=question,
            payload={
                "question": question,
                "options": _options_tuple(getattr(action, "options", ())),
                "prompt_kind": _string_value(getattr(action, "prompt_kind", "")),
                "tool_name": _string_value(getattr(action, "tool", "")),
                "method": _string_value(getattr(action, "method", "")),
            },
        )
    if action_kind == "done":
        message = _string_value(getattr(action, "message", ""))
        return TaskEvent(task_id=task_id, kind=TaskEventKind.DONE, message=message, payload={"message": message})
    if action_kind == "error":
        message = _string_value(getattr(action, "message", ""))
        return TaskEvent(task_id=task_id, kind=TaskEventKind.ERROR, message=message, payload={"message": message})
    if action_kind == "running":
        return TaskEvent(task_id=task_id, kind=TaskEventKind.RUNNING, payload={})
    if action_kind == "cancelled":
        message = _string_value(getattr(action, "message", ""), "Task cancelled") or "Task cancelled"
        return TaskEvent(task_id=task_id, kind=TaskEventKind.CANCELLED, message=message, payload={"message": message})
    return None


def task_status_payload_to_task_event(payload: Mapping[str, Any]) -> TaskEvent | None:
    """Convert Gateway/MCP task status payloads into neutral TaskEvent values."""

    task_id = _string_value(payload.get("task_id"))
    if not task_id:
        return None

    status = _string_value(payload.get("status"))
    copied = _copy_payload(payload)
    if "options" in copied:
        copied["options"] = _options_tuple(copied.get("options"))

    if status == "waiting":
        prompt_kind = _string_value(payload.get("kind") or payload.get("prompt_kind") or "waiting")
        copied["prompt_kind"] = prompt_kind
        return TaskEvent(
            task_id=task_id,
            kind=TaskEventKind.WAITING,
            message=_string_value(payload.get("question")),
            payload=copied,
        )
    if status == "running":
        return TaskEvent(task_id=task_id, kind=TaskEventKind.RUNNING, payload=copied)
    if status == "done":
        return TaskEvent(
            task_id=task_id,
            kind=TaskEventKind.DONE,
            message=_string_value(payload.get("result")),
            payload=copied,
        )
    if status == "error":
        return TaskEvent(
            task_id=task_id,
            kind=TaskEventKind.ERROR,
            message=_string_value(payload.get("message")),
            payload=copied,
        )
    if status == "cancelled":
        return TaskEvent(
            task_id=task_id,
            kind=TaskEventKind.CANCELLED,
            message=_string_value(payload.get("message"), "Task cancelled") or "Task cancelled",
            payload=copied,
        )
    return None
