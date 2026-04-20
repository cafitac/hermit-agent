from __future__ import annotations
import asyncio
import concurrent.futures
import logging
import os
import time
from typing import Any

from ..llm_client import create_llm_client
from ..agent_session import MCPAgentSession
from ..codex_runner import is_codex_model, run_codex_task
from ._singletons import sse_manager, MAX_WORKERS
from .task_models import AUTO_MODEL_SENTINEL, normalize_requested_model
from .sse import SSEEvent, SSEManager
from .task_store import GatewayTaskState, release_worker_slot
from .permission import GatewayPermissionChecker
from .db import insert_usage
from .session_log import GatewaySessionLog

logger = logging.getLogger("hermit_agent.gateway.runner")

_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=MAX_WORKERS,
    thread_name_prefix="gateway-agent",
)

def _is_auto_model(model: str) -> bool:
    normalized = normalize_requested_model(model).lower()
    return normalized in {"auto", AUTO_MODEL_SENTINEL}


def _is_unavailable_error(error: Exception | str) -> bool:
    text = str(error).lower()
    markers = [
        "rate-limit",
        "rate limit",
        "out of credits",
        "insufficient",
        "quota",
        "authentication",
        "unauthorized",
        "forbidden",
        "api key",
        "requested model unavailable",
        "no provider configured",
        "model not found",
        "unknown model",
        "http 401",
        "http 403",
        "http 429",
        "connection refused",
        "failed to establish a new connection",
        "could not connect",
    ]
    return any(marker in text for marker in markers)


def _auto_model_chain(cfg: dict[str, Any]) -> list[dict[str, str]]:
    from ..config import get_routing_priority_models

    configured = get_routing_priority_models(cfg, available_only=True)
    if configured:
        return configured
    return get_routing_priority_models(cfg, available_only=False)


def _make_emitter_handler(task_id: str, sse: SSEManager, gw_log: GatewaySessionLog | None = None):
    """Handler that converts AgentLoop emitter events to SSE events.
    Also forwards non-streaming events to the GatewaySessionLog."""

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
        # Forward non-streaming events to gateway session log
        if gw_log is not None and event_type not in ("streaming", "stream_end"):
            gw_log.write_event({"type": event_type, **data})
        # progress events are handled by the existing progress_hook

    return handler


def _run(
    task_id: str,
    task: str,
    cwd: str,
    user: str,
    model: str,
    max_turns: int,
    state: GatewayTaskState,
    sse: SSEManager,
) -> dict:
    """Runs in the executor thread. Always calls release_worker_slot() in finally."""
    from ..permissions import PermissionMode
    from ..config import load_settings, select_llm_endpoint

    requested_model = normalize_requested_model(model)
    cfg = load_settings(cwd=cwd)

    gw_log = GatewaySessionLog(
        task_id=task_id,
        cwd=cwd,
        model=requested_model,
        parent_session_id=state.parent_session_id,
    )

    def _run_single(selected_model: str, reasoning_effort: str | None = None) -> dict[str, Any]:
        if is_codex_model(selected_model):
            result = run_codex_task(
                task_id=task_id,
                task=task,
                cwd=cwd,
                model=selected_model,
                reasoning_effort=reasoning_effort or cfg.get("codex_reasoning_effort"),
                state=state,
                sse=sse,
                gw_log=gw_log,
                codex_command=cfg.get("codex_command", "codex"),
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

        llm = create_llm_client(base_url=llm_url, model=selected_model, api_key=api_key)

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

        checker = GatewayPermissionChecker(
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
            except Exception as e:
                logger.warning("slash command preprocessing failed: %s", e)

        session = MCPAgentSession(
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

        # Per-task structured event logging (additive — does not replace stdlib logger or SSE)
        session.set_emitter_handler(_make_emitter_handler(task_id, sse, gw_log))

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

    try:
        if _is_auto_model(requested_model):
            attempted: list[str] = []
            unavailable: list[dict[str, str]] = []

            for route in _auto_model_chain(cfg):
                selected_model = route["model"]
                reasoning_effort = route.get("reasoning_effort")
                attempted.append(selected_model)
                gw_log.write_event({
                    "type": "model_attempt",
                    "model": selected_model,
                    **({"reasoning_effort": reasoning_effort} if reasoning_effort else {}),
                })
                try:
                    result = _run_single(selected_model, reasoning_effort)
                    gw_log.mark_completed(state.token_totals)
                    return result | {
                        "model": selected_model,
                        "auto_route": {
                            "requested": requested_model,
                            "attempted": attempted,
                            "selected": selected_model,
                        },
                    }
                except Exception as e:
                    message = str(e)
                    unavailable.append({"model": selected_model, "error": message})
                    gw_log.write_event({
                        "type": "model_attempt_failed",
                        "model": selected_model,
                        "error": message,
                        "unavailable": _is_unavailable_error(e),
                    })
                    if state.cancel_event.is_set():
                        raise
                    if not _is_unavailable_error(e):
                        raise

            details = "; ".join(f"{x['model']}: {x['error']}" for x in unavailable)
            raise RuntimeError(f"All auto-routed models unavailable. {details}")

        result = _run_single(requested_model)
        gw_log.mark_completed(state.token_totals)
        return result

    except Exception as e:
        message = str(e)
        if not _is_auto_model(requested_model) and _is_unavailable_error(e):
            message = f"Requested model unavailable: {requested_model}. {message}"

        logger.exception("task %s failed (model=%s): %s", task_id, requested_model, message)
        state.status = "error"
        state.waiting_kind = None
        state.result = message
        state.result_queue.put({"status": "error", "message": message})
        sse.publish_threadsafe(task_id, SSEEvent(type="error", message=message))
        gw_log.mark_crashed(message)
        return {
            "token_totals": state.token_totals,
            "status": state.status,
            "model": requested_model,
        }
    finally:
        release_worker_slot()


async def run_task_async(
    task_id: str,
    task: str,
    cwd: str,
    user: str,
    model: str,
    max_turns: int,
    state: GatewayTaskState,
) -> None:
    """FastAPI background task. Runs _run() in executor, then records usage in DB."""
    start_ms = int(time.monotonic() * 1000)

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _EXECUTOR,
        _run,
        task_id, task, cwd, user, model, max_turns, state, sse_manager,
    )

    duration_ms = int(time.monotonic() * 1000) - start_ms
    totals = result.get("token_totals", {})
    final_status = result.get("status", "done")

    try:
        await insert_usage(
            user=user,
            task_id=task_id,
            model=result.get("model", model),
            prompt_tokens=totals.get("prompt_tokens", 0),
            completion_tokens=totals.get("completion_tokens", 0),
            duration_ms=duration_ms,
            status=final_status,
        )
    except Exception as e:
        logger.warning("insert_usage failed for %s: %s", task_id, e)
