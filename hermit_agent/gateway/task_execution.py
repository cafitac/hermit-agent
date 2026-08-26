from __future__ import annotations

from typing import Any

from ..agent_session import MCPAgentSession
from ..llm_client import create_llm_client
from .permission import GatewayPermissionChecker
from .session_log import GatewaySessionLog
from .sse import SSEEvent, SSEManager
from .task_store import GatewayTaskState


def _run_readonly_role(*, llm, cwd: str, system_prompt: str, prompt: str, max_turns: int) -> str:
    """Run a planning/review role with no write or shell tools."""
    from ..loop import AgentLoop
    from ..permissions import PermissionMode
    from ..tools import create_default_tools

    readonly_tools = [tool for tool in create_default_tools(cwd=cwd) if getattr(tool, "read_only", False)]

    agent = AgentLoop(
        llm=llm,
        tools=readonly_tools,
        cwd=cwd,
        permission_mode=PermissionMode.ALLOW_READ,
        system_prompt=system_prompt,
        session_kind="gateway",
    )
    agent.MAX_TURNS = min(max_turns, 20)
    agent.streaming = False
    return agent.run(prompt)


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
                    "permission", "version", "modified_files",
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
    provider: str | None = None,
    orchestration_plan=None,
    llm_factory=create_llm_client,
    session_cls=MCPAgentSession,
    permission_checker_cls=GatewayPermissionChecker,
):
    from ..permissions import PermissionMode

    gw_log.write_event(
        {
            "type": "execution_route",
            "requested_model": selected_model,
            "route": "mcp_session",
        }
    )

    if provider:
        llm_url, api_key = select_llm_endpoint(selected_model, cfg, provider=provider)
    else:
        llm_url, api_key = select_llm_endpoint(selected_model, cfg)
    if not llm_url:
        raise RuntimeError(f"Requested model unavailable: {selected_model} (no provider configured)")

    llm = llm_factory(base_url=llm_url, model=selected_model, api_key=api_key)

    plan_text = ""
    if orchestration_plan is not None and "planner" in orchestration_plan.stages:
        from ..orchestration import PLANNER_SYSTEM_PROMPT

        state.orchestration["active_stage"] = "planner"
        sse.publish_threadsafe(task_id, SSEEvent(type="progress", step="planner", message="Preparing an implementation plan."))
        plan_text = _run_readonly_role(
            llm=llm,
            cwd=cwd,
            system_prompt=PLANNER_SYSTEM_PROMPT,
            prompt=f"Task:\n{task}",
            max_turns=max_turns,
        )
        state.orchestration["completed_stages"] = ["planner"]

    def notify_fn(question: str, options: list, *, tool_name: str = "ask", method: str = "") -> None:
        state.status = "waiting"
        state.waiting_kind = "waiting"
        state.waiting_prompt = {"question": question, "options": options or [], "tool_name": tool_name, "method": method}
        sse.publish_threadsafe(task_id, SSEEvent(
            type="waiting", question=question, options=options or [], tool_name=tool_name, method=method,
        ))

    def permission_notify_fn(question: str, options: list, *, tool_name: str = "bash", method: str = "") -> None:
        state.status = "waiting"
        state.waiting_kind = "permission_ask"
        state.waiting_prompt = {"question": question, "options": options or [], "tool_name": tool_name, "method": method}
        sse.publish_threadsafe(task_id, SSEEvent(
            type="permission_ask", question=question, options=options or [], tool_name=tool_name, method=method,
        ))

    def notify_running_fn() -> None:
        state.status = "running"
        state.waiting_kind = None
        state.waiting_prompt = None

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
    if plan_text:
        processed_task = f"{task}\n\n<implementation_plan>\n{plan_text}\n</implementation_plan>\n\nExecute the task and verify the changed behavior."
    session = session_cls(
        llm=llm,
        cwd=cwd,
        state=state,
        task_id=task_id,
        notify_fn=notify_fn,
        notify_running_fn=notify_running_fn,
        make_progress_hook_fn=make_progress_hook_fn,
        notify_done_fn=(
            (lambda _tid, _summary: None)
            if orchestration_plan is not None and orchestration_plan.quality_gate
            else lambda tid, summary: sse.publish_threadsafe(tid, SSEEvent(type="done", result=summary or ""))
        ),
        notify_error_fn=lambda tid, msg: sse.publish_threadsafe(
            tid, SSEEvent(type="error", message=msg),
        ),
        permission_checker=checker,
        max_turns=max_turns,
        parent_session_id=state.parent_session_id,
        task_mode=None,
    )

    session.set_emitter_handler(make_emitter_handler(task_id, sse, gw_log))
    session.run(processed_task)

    if (
        orchestration_plan is not None
        and orchestration_plan.quality_gate
        and not state.cancel_event.is_set()
        and state.status not in ("error", "cancelled")
    ):
        from ..orchestration import REVIEWER_SYSTEM_PROMPT, review_requires_attention

        state.orchestration["active_stage"] = "reviewer"
        sse.publish_threadsafe(task_id, SSEEvent(type="progress", step="reviewer", message="Reviewing the completed change."))
        agent = getattr(session, "_agent", None)
        modified_files = list(getattr(agent, "modified_files", []))
        review = _run_readonly_role(
            llm=llm,
            cwd=cwd,
            system_prompt=REVIEWER_SYSTEM_PROMPT,
            prompt=(
                f"Original task:\n{task}\n\n"
                f"Files reported by the executor:\n" + ("\n".join(f"- {path}" for path in modified_files) or "- No file list was reported")
            ),
            max_turns=max_turns,
        )
        completed = list(state.orchestration.get("completed_stages", []))
        state.orchestration["completed_stages"] = [*completed, "executor", "reviewer"]
        state.orchestration["review"] = review
        if review_requires_attention(review):
            state.status = "needs_review"
        else:
            state.status = "done"
        state.orchestration.pop("active_stage", None)
        state.result = f"{state.result or '[task complete]'}\n\n[Quality review]\n{review}"
        sse.publish_threadsafe(task_id, SSEEvent(type=state.status, result=state.result))

    if state.cancel_event.is_set():
        state.status = "cancelled"
        state.waiting_kind = None
        state.waiting_prompt = None
    elif state.status not in ("done", "error", "needs_review"):
        state.status = "done"
        state.waiting_kind = None
        state.waiting_prompt = None

    return {
        "token_totals": state.token_totals,
        "status": state.status,
        "model": selected_model,
    }
