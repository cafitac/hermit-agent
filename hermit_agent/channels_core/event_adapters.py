from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping


@dataclass(frozen=True)
class ChannelAction:
    kind: Literal["prompt", "done", "error", "running"]
    question: str = ""
    options: tuple[str, ...] = ()
    message: str = ""
    prompt_kind: Literal["waiting", "permission_ask"] | str = ""
    tool: str = ""
    method: str = ""


def _prompt_fields(event: Mapping[str, Any]) -> tuple[str, list[str], str, str] | None:
    event_type = event.get("type", "")
    if event_type not in ("waiting", "permission_ask"):
        return None
    return (
        event.get("question", ""),
        list(event.get("options", []) or []),
        "ask" if event_type == "waiting" else event.get("tool_name", "bash"),
        str(event.get("method", "") or ""),
    )


def bridge_messages_from_sse_event(
    event: Mapping[str, Any],
    *,
    now: Callable[[], float] | None = None,
) -> list[dict[str, Any]]:
    """Translate a gateway SSE event into bridge/TUI JSON messages."""
    now_fn = now or time.time
    event_type = event.get("type")

    if event_type == "streaming":
        return [{"type": "streaming", "token": event.get("token", "")}]
    if event_type == "stream_end":
        return [{"type": "stream_end"}]
    if event_type == "tool_use":
        return [{
            "type": "tool_use",
            "name": event.get("tool_name", ""),
            "detail": event.get("detail", ""),
            "ts": now_fn(),
        }]
    if event_type == "tool_result":
        return [{
            "type": "tool_result",
            "content": event.get("content", ""),
            "is_error": event.get("is_error", False),
            "ts": now_fn(),
        }]
    if event_type == "status":
        fields = {k: v for k, v in event.items() if k not in ("type", "_source")}
        return [{"type": "status", **fields}]
    if event_type == "model_changed":
        return [{
            "type": "model_changed",
            "old_model": event.get("old_model", ""),
            "new_model": event.get("new_model", ""),
        }]
    if event_type == "progress":
        return [{
            "type": "tool_result",
            "content": event.get("message", ""),
            "is_error": False,
        }]
    if event_type == "error":
        return [{"type": "error", "message": event.get("message", "")}]

    prompt = _prompt_fields(event)
    if prompt is not None:
        question, options, tool, _method = prompt
        return [{
            "type": "permission_ask",
            "tool": tool,
            "summary": question,
            "options": options,
        }]

    return []


def channel_action_from_sse_event(event: Mapping[str, Any]) -> ChannelAction | None:
    """Interpret SSE events into MCP-channel side effects."""
    prompt = _prompt_fields(event)
    if prompt is not None:
        question, options, tool, method = prompt
        return ChannelAction(
            kind="prompt",
            question=question,
            options=tuple(options),
            prompt_kind=str(event.get("type", "")),
            tool=tool,
            method=method,
        )

    event_type = event.get("type", "")
    if event_type == "done":
        return ChannelAction(kind="done", message=event.get("result", ""))
    if event_type == "error":
        return ChannelAction(kind="error", message=event.get("message", ""))
    if event_type == "cancelled":
        return ChannelAction(kind="error", message=event.get("message", "Task cancelled"))
    if event_type == "reply_ack":
        return ChannelAction(kind="running")
    return None
