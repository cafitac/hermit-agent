from __future__ import annotations
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .._singletons import sse_manager
from .. import task_commands as _task_commands
from ..task_store import acquire_worker_slot, get_task
from ..task_actions import cancel_task_state, enqueue_reply, is_waiting_for_reply
from ..task_runtime import prepare_task_launch
from ..task_views import add_waiting_prompt_fields
from ..auth import AuthContext, get_current_user
from ..errors import ErrorCode, gateway_error
from ..task_runner import run_task_async

router = APIRouter()


def _discover_available_models() -> list[dict[str, object]]:
    return _task_commands._discover_available_models()


def _handle_slash_command(text: str) -> str | None:
    return _task_commands._handle_slash_command(text, discover_available_models=_discover_available_models)


class TaskRequest(BaseModel):
    task: str
    cwd: str = ""
    model: str = ""
    max_turns: int = 200
    parent_session_id: str | None = None


class ReplyRequest(BaseModel):
    message: str


@router.get("/models")
async def list_models():
    """Return available models from the configured LLM."""
    return {"models": _discover_available_models()}


@router.post("/tasks")
async def create_task_endpoint(
    req: TaskRequest,
    background: BackgroundTasks,
    auth: AuthContext = Depends(get_current_user),
):
    # Handle slash commands immediately (bypass AgentLoop)
    task_text = req.task.strip()
    if task_text.startswith("/"):
        instant_result = _handle_slash_command(task_text)
        if instant_result is not None:
            return {"task_id": "instant", "status": "done", "result": instant_result}

    if not acquire_worker_slot():
        raise gateway_error(ErrorCode.SERVER_BUSY)

    launch = prepare_task_launch(
        task=req.task,
        cwd=req.cwd,
        model=req.model,
        max_turns=req.max_turns,
        user=auth.user,
        parent_session_id=req.parent_session_id,
    )

    background.add_task(
        run_task_async,
        task_id=launch.task_id,
        task=launch.task,
        cwd=launch.cwd,
        user=launch.user,
        model=launch.model,
        max_turns=launch.max_turns,
        state=launch.state,
    )

    return {"task_id": launch.task_id, "status": "running"}


@router.get("/tasks/{task_id}/stream")
async def stream_task(
    task_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    state = get_task(task_id)
    if not state:
        raise gateway_error(ErrorCode.TASK_NOT_FOUND)

    return StreamingResponse(
        sse_manager.stream(task_id),
        media_type="text/event-stream",
        headers={
            "X-Task-ID": task_id,
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/tasks/{task_id}/reply")
async def reply_task(
    task_id: str,
    req: ReplyRequest,
    auth: AuthContext = Depends(get_current_user),
):
    from ..sse import SSEEvent

    state = get_task(task_id)
    if not state:
        raise gateway_error(ErrorCode.TASK_NOT_FOUND)
    if not is_waiting_for_reply(state):
        raise gateway_error(
            ErrorCode.TASK_ALREADY_DONE,
            f"Task status is '{state.status}'. Reply is only possible in waiting state.",
        )

    enqueue_reply(state, req.message)
    sse_manager.publish_threadsafe(task_id, SSEEvent(type="reply_ack", message="reply received"))
    return {"status": "ok", "task_id": task_id}


@router.delete("/tasks/{task_id}")
async def cancel_task(
    task_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    state = get_task(task_id)
    if not state:
        raise gateway_error(ErrorCode.TASK_NOT_FOUND)

    cancel_task_state(state)
    return {"status": "cancelled", "task_id": task_id}


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    state = get_task(task_id)
    if not state:
        raise gateway_error(ErrorCode.TASK_NOT_FOUND)

    result = {
        "task_id": task_id,
        "status": state.status,
        "result": state.result,
        "token_totals": state.token_totals,
    }
    return add_waiting_prompt_fields(result, state, include_kind=True)
