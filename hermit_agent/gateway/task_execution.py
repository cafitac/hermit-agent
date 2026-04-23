from __future__ import annotations

import re
from queue import Empty
from typing import Any

from ..agent_session import MCPAgentSession
from ..codex_runner import is_codex_model, run_codex_task, wait_for_codex_host_reply
from ..config import get_routing_priority_models, is_model_configured
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

    def _parse_execution_mode_hint(task_text: str) -> tuple[str | None, str]:
        text = task_text or ""
        pattern = re.compile(r"^\s*(?:\[)?\s*hermit-execution-mode\s*:\s*(interview|codex|auto)\s*(?:\])?\s*$", re.IGNORECASE)
        lines = text.splitlines()
        kept: list[str] = []
        override: str | None = None
        for line in lines:
            match = pattern.match(line.strip())
            if match and override is None:
                override = match.group(1).lower()
                continue
            kept.append(line)
        normalized = "\n".join(kept).strip()
        return override, normalized

    def _parse_interview_question_hint(task_text: str) -> tuple[str | None, str]:
        text = task_text or ""
        pattern = re.compile(r"^\s*(?:\[)?\s*hermit-interview-question\s*:\s*(.+?)\s*(?:\])?\s*$", re.IGNORECASE)
        lines = text.splitlines()
        kept: list[str] = []
        question: str | None = None
        for line in lines:
            match = pattern.match(line.strip())
            if match and question is None:
                question = match.group(1).strip()
                continue
            kept.append(line)
        normalized = "\n".join(kept).strip()
        return question, normalized

    def _needs_interview_session(task_text: str) -> bool:
        text = (task_text or "").strip().lower()
        if not text:
            return False
        phrases = (
            "ask the user",
            "ask exactly one short user question",
            "need one missing input",
            "wait for the reply",
            "wait for their response",
            "through the host interactive input surface",
            "ask_user_question",
            "deep interview",
            "심층인터뷰",
            "추가 사용자 입력",
            "사용자에게 질문",
        )
        return any(phrase in text for phrase in phrases)

    def _select_interview_model(cfg: dict[str, Any], selected_model: str) -> str | None:
        if not is_codex_model(selected_model) and is_model_configured(selected_model, cfg):
            return selected_model
        for route in get_routing_priority_models(cfg, available_only=True):
            model = route["model"]
            if is_codex_model(model):
                continue
            return model
        fallback = str(cfg.get("model") or "").strip()
        if fallback and not is_codex_model(fallback) and is_model_configured(fallback, cfg):
            return fallback
        return None

    def _extract_followup_question(result_text: str) -> str | None:
        text = (result_text or "").strip()
        lowered = text.lower()
        if not text or len(text) > 500 or "```" in text:
            return None
        if "i don't have access to an interactive input surface" in lowered:
            return text
        if "please provide" in lowered and "?" in text:
            return text
        if text.endswith("?"):
            return text
        return None

    def _derive_interview_question(task_text: str) -> str:
        hinted_question, stripped = _parse_interview_question_hint(task_text)
        if hinted_question:
            return hinted_question

        quoted = re.search(r"['\"]([^'\"]+\?)['\"]", stripped)
        if quoted:
            return quoted.group(1).strip()

        lowered = stripped.lower()
        if "environment" in lowered:
            return "Which environment should we use?"
        if "branch" in lowered:
            return "Which branch should we use?"
        if "ticket" in lowered or "jira" in lowered:
            return "Which ticket should we use?"
        return "What input should I use to continue this task?"

    def _wait_for_gateway_reply(question: str) -> str:
        state.status = "waiting"
        state.waiting_kind = "waiting"
        state.waiting_prompt = {"question": question, "options": [], "tool_name": "ask"}
        sse.publish_threadsafe(task_id, SSEEvent(type="waiting", question=question, options=[], tool_name="ask"))
        while True:
            if state.cancel_event.is_set():
                state.status = "cancelled"
                state.waiting_kind = None
                state.waiting_prompt = None
                raise RuntimeError("Task cancelled while waiting for interview input.")
            try:
                answer = state.reply_queue.get(timeout=0.25)
            except Empty:
                continue
            if answer == "__CANCELLED__":
                state.status = "cancelled"
                state.waiting_kind = None
                state.waiting_prompt = None
                raise RuntimeError("Task cancelled while waiting for interview input.")
            state.status = "running"
            state.waiting_kind = None
            state.waiting_prompt = None
            sse.publish_threadsafe(task_id, SSEEvent(type="reply_ack", message="reply received"))
            return str(answer)

    execution_mode_hint, normalized_task = _parse_execution_mode_hint(task)
    route_reason = "default"
    if execution_mode_hint == "interview":
        route_interview_to_session = is_codex_model(selected_model)
        route_reason = "explicit-interview-hint"
    elif execution_mode_hint == "codex":
        route_interview_to_session = False
        route_reason = "explicit-codex-hint"
    else:
        route_interview_to_session = is_codex_model(selected_model) and _needs_interview_session(normalized_task)
        if route_interview_to_session:
            route_reason = "interview-heuristic"

    task = normalized_task

    if route_interview_to_session:
        gw_log.write_event(
            {
                "type": "execution_route",
                "requested_model": selected_model,
                "route": "mcp_session",
                "reason": route_reason,
            }
        )
    elif is_codex_model(selected_model):
        gw_log.write_event(
            {
                "type": "execution_route",
                "requested_model": selected_model,
                "route": "codex_runner",
                "reason": route_reason,
            }
        )
    else:
        gw_log.write_event(
            {
                "type": "execution_route",
                "requested_model": selected_model,
                "route": "mcp_session",
                "reason": "non-codex-model",
            }
        )

    if is_codex_model(selected_model) and not route_interview_to_session:
        active_task = task
        result = None
        for _ in range(3):
            result = codex_runner(
                task_id=task_id,
                task=active_task,
                cwd=cwd,
                model=selected_model,
                reasoning_effort=reasoning_effort or cfg.get("codex_reasoning_effort"),
                state=state,
                sse=sse,
                gw_log=gw_log,
                codex_command=cfg.get("codex_command", "codex"),
                codex_channels_cfg=cfg,
            )
            followup_question = _extract_followup_question(str(result.get("result", "")))
            if not followup_question or state.cancel_event.is_set():
                break
            answer = wait_for_codex_host_reply(
                state=state,
                sse=sse,
                task_id=task_id,
                question=followup_question,
                cwd=cwd,
            )
            active_task = (
                f"{task}\n\nAdditional user input received during execution:\n{answer}\n\n"
                "Continue from that answer and provide the final result only."
            )
        assert result is not None
        if state.cancel_event.is_set():
            state.status = "cancelled"
            state.waiting_kind = None
            state.waiting_prompt = None
        else:
            state.status = "done"
            state.waiting_prompt = None
            sse.publish_threadsafe(task_id, SSEEvent(type="done", result=result.get("result", "")))
        return result | {"status": state.status, "token_totals": state.token_totals, "model": selected_model}

    session_model = selected_model
    if route_interview_to_session:
        interview_model = _select_interview_model(cfg, selected_model)
        if not interview_model:
            raise RuntimeError(
                "Interview-style Codex task requires a non-Codex configured model for MCPAgentSession fallback."
            )
        session_model = interview_model
        interview_question = _derive_interview_question(task)
        gw_log.write_event(
            {
                "type": "pre_interview_question",
                "question": interview_question,
            }
        )
        interview_answer = _wait_for_gateway_reply(interview_question)
        gw_log.write_event(
            {
                "type": "pre_interview_answer",
                "answer": interview_answer,
            }
        )
        task = (
            f"{task}\n\nRequired user input already collected:\n"
            f"Question: {interview_question}\n"
            f"Answer: {interview_answer}\n\n"
            "Continue from that answer. Do not ask the same question again."
        )

    llm_url, api_key = select_llm_endpoint(session_model, cfg)
    if not llm_url:
        raise RuntimeError(f"Requested model unavailable: {session_model} (no provider configured)")

    llm = llm_factory(base_url=llm_url, model=session_model, api_key=api_key)

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
        task_mode="interview" if route_interview_to_session else None,
    )

    session.set_emitter_handler(make_emitter_handler(task_id, sse, gw_log))
    session.run(processed_task)

    if state.cancel_event.is_set():
        state.status = "cancelled"
        state.waiting_kind = None
        state.waiting_prompt = None
    elif state.status not in ("done", "error"):
        state.status = "done"
        state.waiting_kind = None
        state.waiting_prompt = None

    return {
        "token_totals": state.token_totals,
        "status": state.status,
        "model": session_model,
    }
