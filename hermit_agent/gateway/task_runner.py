from __future__ import annotations
import asyncio
import concurrent.futures
import logging
import os
import time
from typing import Any

from ..agent_session import MCPAgentSession
from ..codex_runner import run_codex_task
from ..llm_client import create_llm_client
from ._singletons import sse_manager, MAX_WORKERS
from .task_models import AUTO_MODEL_SENTINEL, normalize_requested_model
from .permission import GatewayPermissionChecker
from .sse import SSEEvent, SSEManager
from .task_store import GatewayTaskState, release_worker_slot
from .db import insert_usage
from .session_log import GatewaySessionLog
from .task_execution import run_single_model

# Re-export patch points used by existing tests. task_execution imports these at call time.
__all__ = ["run_codex_task", "MCPAgentSession", "GatewayPermissionChecker", "create_llm_client", "SSEEvent"]

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
    from ..config import load_settings, select_llm_endpoint

    requested_model = normalize_requested_model(model)
    cfg = load_settings(cwd=cwd)

    gw_log = GatewaySessionLog(
        task_id=task_id,
        cwd=cwd,
        model=requested_model,
        parent_session_id=state.parent_session_id,
    )

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
                    result = run_single_model(
                        task_id=task_id,
                        task=task,
                        cwd=cwd,
                        selected_model=selected_model,
                        reasoning_effort=reasoning_effort,
                        max_turns=max_turns,
                        state=state,
                        sse=sse,
                        gw_log=gw_log,
                        cfg=cfg,
                        select_llm_endpoint=select_llm_endpoint,
                        codex_runner=run_codex_task,
                        llm_factory=create_llm_client,
                        session_cls=MCPAgentSession,
                        permission_checker_cls=GatewayPermissionChecker,
                    )
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

        result = run_single_model(
            task_id=task_id,
            task=task,
            cwd=cwd,
            selected_model=requested_model,
            reasoning_effort=None,
            max_turns=max_turns,
            state=state,
            sse=sse,
            gw_log=gw_log,
            cfg=cfg,
            select_llm_endpoint=select_llm_endpoint,
            codex_runner=run_codex_task,
            llm_factory=create_llm_client,
            session_cls=MCPAgentSession,
            permission_checker_cls=GatewayPermissionChecker,
        )
        gw_log.mark_completed(state.token_totals)
        return result

    except Exception as e:
        message = str(e)
        if not _is_auto_model(requested_model) and _is_unavailable_error(e):
            message = f"Requested model unavailable: {requested_model}. {message}"

        logger.exception("task %s failed (model=%s): %s", task_id, requested_model, message)
        state.status = "error"
        state.waiting_kind = None
        state.waiting_prompt = None
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
