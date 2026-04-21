from __future__ import annotations

from typing import Any

from ..agent_session import MCPAgentSession
from ..codex_runner import is_codex_model, run_codex_task
from ..llm_client import create_llm_client
from .permission import GatewayPermissionChecker
from .session_log import GatewaySessionLog
from .sse import SSEEvent, SSEManager
from .task_store import GatewayTaskState


def make_emitter_handler(task_id: str, sse: SSEManager, gw_log: GatewaySessionLog | None = None):
    """Handler that converts AgentLoop emitter events to SSE events."""

    def handler(event_type: str, data: dict):
        if event_type == "streaming":
            sse.publish_threadsafe(task_id, SSEEvent(type="streaming", token=data.get("token", "")))
        elif event_type == "stream_end":
            sse.publish_threadsafe(task_id, SSEEvent(type="stream_end"))
        elif event_type == "tool_use":
            sse.publish_threadsafe(task_id, SSEEvent(
                type="tool_use", tool_name=data.get("name", ""), detail=data.get("detail", ""),
            ))
        elif event_type == "tool_result":
            sse.publish_threadsafe(task_id, SSEEvent(
                type="tool_result", content=data.get("content", ""), is_error=data.get("is_error", False),
            ))
        elif event_type == "model_changed":
            sse.publish_threadsafe(task_id, SSEEvent(
                type="model_changed", old_model=data.get("old_model", ""), new_model=data.get("new_model", ""),
            ))
        elif event_type == "status":
            status_fields = {
                k: data[k] for k in (
                    "turns", "ctx_pct", "tokens", "model", "session_id",
                    "permission", "version", "auto_agents", "modified_files",
                ) if k in data
            }
            sse.publish_threadsafe(task_id, SSEEvent(type="status", **status_fields))
        if gw_log is not None and event_type not in ("streaming", "stream_end"):
            gw_log.write_event({"type": event_type, **data})

    return handler


def run_single_model(
    *,
    task_id: str,
    task: str,
    cwd: str,
    selected_model: str,
    reasoning_effort: str | None,
    max_turns: int,
    state: GatewayTaskState,
    sse: SSEManager,
    gw_log: GatewaySessionLog,
    cfg: dict[str, Any],
    select_llm_endpoint,
    codex_runner=run_codex_task,
    llm_factory=create_llm_client,
    session_cls=MCPAgentSession,
    permission_checker_cls=GatewayPermissionChecker,
):
    from ..permissions import PermissionMode

    if is_codex_model(selected_model):
        result = codex_runner(
            task_id=task_id,
            task=task,
            cwd=cwd,
            model=selected_model,
            reasoning_effort=reasoning_effort or cfg.get("codex_reasoning_effort"),
            state=state,
            sse=sse,
            gw_log=gw_log,
            codex_command=cfg.get("codex_command", "codex"),
            codex_channels_cfg=cfg,
        )
        if state.cancel_event.is_set():
            state.status = "cancelled"
            state.waiting_kind = None
        else:
            state.status = "done"
            sse.publish_threadsafe(task_id, SSEEvent(type="done", result=result.get("result", "")))
        return result | {"status": state.status, "token_totals": state.token_totals, "model": selected_model}

    llm_url, api_key = select_llm_endpoint(selected_model, cfg)
    if not llm_url:
        raise RuntimeError(f"Requested model unavailable: {selected_model} (no provider configured)")

    llm = llm_factory(base_url=llm_url, model=selected_model, api_key=api_key)

    def notify_fn(question: str, options: list) -> None:
        state.status = "waiting"
        state.waiting_kind = "waiting"
        sse.publish_threadsafe(task_id, SSEEvent(
            type="waiting", question=question, options=options or [],
        ))

    def permission_notify_fn(question: str, options: list) -> None:
        state.status = "waiting"
        state.waiting_kind = "permission_ask"
        sse.publish_threadsafe(task_id, SSEEvent(
            type="permission_ask", question=question, options=options or [],
        ))

    def notify_running_fn() -> None:
        state.status = "running"
        state.waiting_kind = None

    def progress_hook(step: str, result: str) -> None:
        sse.publish_threadsafe(task_id, SSEEvent(
            type="progress", step=step, message=result[:500],
        ))

    def make_progress_hook_fn(_tid: str):
        return progress_hook

    checker = permission_checker_cls(
        mode=PermissionMode.ALLOW_READ,
        question_queue=state.question_queue,
        reply_queue=state.reply_queue,
        notify_fn=notify_fn,
        notify_running_fn=notify_running_fn,
        permission_notify_fn=permission_notify_fn,
    )

    processed_task = task
    if processed_task.strip().startswith("/"):
        slash_line = processed_task.strip().splitlines()[0]
        try:
            from ..loop import _preprocess_slash_command

            processed_task = _preprocess_slash_command(processed_task, slash_line, cwd)
        except Exception:
            pass

    session = session_cls(
        llm=llm,
        cwd=cwd,
        state=state,
        task_id=task_id,
        notify_fn=notify_fn,
        notify_running_fn=notify_running_fn,
        make_progress_hook_fn=make_progress_hook_fn,
        notify_done_fn=lambda tid, summary: sse.publish_threadsafe(
            tid, SSEEvent(type="done", result=summary or ""),
        ),
        notify_error_fn=lambda tid, msg: sse.publish_threadsafe(
            tid, SSEEvent(type="error", message=msg),
        ),
        permission_checker=checker,
        max_turns=max_turns,
        parent_session_id=state.parent_session_id,
    )

    session.set_emitter_handler(make_emitter_handler(task_id, sse, gw_log))
    session.run(processed_task)

    if state.cancel_event.is_set():
        state.status = "cancelled"
        state.waiting_kind = None
    elif state.status not in ("done", "error"):
        state.status = "done"
        state.waiting_kind = None

    return {
        "token_totals": state.token_totals,
        "status": state.status,
        "model": selected_model,
    }
