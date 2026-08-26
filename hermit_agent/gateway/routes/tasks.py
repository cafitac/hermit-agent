from __future__ import annotations
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .._singletons import sse_manager
from ..task_store import acquire_worker_slot
from ..task_actions import is_waiting_for_reply
from ..task_api import GatewayTaskAPI
from ..auth import AuthContext, get_current_user
from ..errors import ErrorCode, gateway_error
from ..task_runner import run_task_async

router = APIRouter()
api = GatewayTaskAPI()


class TaskRequest(BaseModel):
    task: str
    cwd: str = ""
    model: str = ""
    max_turns: int = 200
    strategy: str = "single"
    parent_session_id: str | None = None


class ReplyRequest(BaseModel):
    message: str


@router.post("/tasks")
async def create_task_endpoint(
    req: TaskRequest,
    background: BackgroundTasks,
    auth: AuthContext = Depends(get_current_user),
):
    if not acquire_worker_slot():
        raise gateway_error(ErrorCode.SERVER_BUSY)

    launch = api.prepare_launch(
        task=req.task,
        cwd=req.cwd,
        model=req.model,
        max_turns=req.max_turns,
        user=auth.user,
        parent_session_id=req.parent_session_id,
        strategy=req.strategy,
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
        strategy=launch.strategy,
    )

    return {"task_id": launch.task_id, "status": "running"}


@router.get("/tasks/{task_id}/stream")
async def stream_task(
    task_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    state = api.get_state(task_id)
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

    state = api.get_state(task_id)
    if not state:
        raise gateway_error(ErrorCode.TASK_NOT_FOUND)
    if not is_waiting_for_reply(state):
        raise gateway_error(
            ErrorCode.TASK_ALREADY_DONE,
            f"Task status is '{state.status}'. Reply is only possible in waiting state.",
        )

    api.reply(state, req.message)
    sse_manager.publish_threadsafe(task_id, SSEEvent(type="reply_ack", message="reply received"))
    return {"status": "ok", "task_id": task_id}


@router.delete("/tasks/{task_id}")
async def cancel_task(
    task_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    state = api.get_state(task_id)
    if not state:
        raise gateway_error(ErrorCode.TASK_NOT_FOUND)
    return api.cancel(state)


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    state = api.get_state(task_id)
    if not state:
        raise gateway_error(ErrorCode.TASK_NOT_FOUND)
    payload = api.status_payload(state, include_kind=True)
    payload.setdefault("result", state.result)
    return payload
