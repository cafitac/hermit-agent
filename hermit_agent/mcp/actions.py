"""Action dispatch helpers for MCP channel events."""

from __future__ import annotations


def dispatch_channel_action(
    *,
    task_id: str,
    action,
    notify_channel,
    notify_done,
    notify_error,
    notify_running,
) -> None:
    if action.kind == 'prompt':
        notify_channel(
            task_id,
            action.question,
            list(action.options),
            prompt_kind=action.prompt_kind,
            tool_name=action.tool,
            method=action.method,
        )
    elif action.kind == 'done':
        notify_done(task_id, action.message[:200] if action.message else None)
    elif action.kind == 'error':
        notify_error(task_id, action.message)
    elif action.kind == 'running':
        notify_running(task_id)
