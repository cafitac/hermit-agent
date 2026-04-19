from __future__ import annotations
import uuid
import logging
import os
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .._singletons import sse_manager
from ..task_store import (
    GatewayTaskState, acquire_worker_slot, create_task, get_task,
)
from ..auth import AuthContext, get_current_user
from ..errors import ErrorCode, gateway_error
from ..task_runner import run_task_async

logger = logging.getLogger("hermit_agent.gateway.routes.tasks")
router = APIRouter()


def _handle_slash_command(text: str) -> str | None:
    """Slash commands that the gateway can handle immediately.
    Returns result text, or None to forward to AgentLoop."""
    parts = text.split(None, 1)
    cmd = parts[0].lower()
    cmd_args = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/help":
        try:
            from ...loop import SLASH_COMMANDS
            lines = ["Available commands:"]
            for name, info in sorted(SLASH_COMMANDS.items()):
                lines.append(f"  /{name:12s} {info['description']}")
            return "\n".join(lines)
        except Exception:
            return "Could not load command list."

    elif cmd == "/model":
        if cmd_args:
            return f"Model changed to {cmd_args}. (Applied from next run)"
        from ...config import load_settings
        cfg = load_settings()
        default_model = cfg.get("model", "")
        lines = ["Available models:"]
        if default_model:
            lines.append(f"  {default_model} (default) [config]")
        # Local ollama models
        try:
            import httpx
            r = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
            if r.status_code == 200:
                for m in r.json().get("models", []):
                    name = m.get("name", "")
                    if name and name != default_model:
                        lines.append(f"  {name} [ollama]")
        except Exception:
            pass
        if len(lines) == 1:
            lines.append("  (No models)")
        return "\n".join(lines)

    elif cmd == "/status":
        return "Gateway mode — /status is not yet supported."

    elif cmd == "/resume":
        return "Gateway mode does not support /resume."

    # Everything else is handled by AgentLoop (skill commands, etc.)
    return None


class TaskRequest(BaseModel):
    task: str
    cwd: str = ""
    model: str = ""
    max_turns: int = 200


class ReplyRequest(BaseModel):
    message: str


@router.get("/models")
async def list_models():
    """Return available models from the configured LLM."""
    from ...config import load_settings
    cfg = load_settings()

    models = []
    default_model = cfg.get("model", "")
    if default_model:
        models.append({"id": default_model, "source": "config", "default": True})

    # Query local ollama models
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
        if r.status_code == 200:
            for m in r.json().get("models", []):
                name = m.get("name", "")
                if name and name != default_model:
                    models.append({"id": name, "source": "ollama", "default": False})
    except Exception:
        pass

    return {"models": models}


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

    task_id = str(uuid.uuid4())
    cwd = req.cwd or os.getcwd()

    from ...config import load_settings
    cfg = load_settings()
    model = req.model or cfg.get("model", "glm-5.1")

    state = create_task(task_id)

    sse_manager.register(task_id)  # register before starting background task to prevent race

    background.add_task(
        run_task_async,
        task_id=task_id,
        task=req.task,
        cwd=cwd,
        user=auth.user,
        model=model,
        max_turns=req.max_turns,
        state=state,
    )

    return {"task_id": task_id, "status": "running"}


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
    if state.status != "waiting":
        raise gateway_error(
            ErrorCode.TASK_ALREADY_DONE,
            f"Task status is '{state.status}'. Reply is only possible in waiting state.",
        )

    state.reply_queue.put(req.message)
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

    state.cancel_event.set()
    # If waiting, send cancellation signal to reply_queue
    if state.status == "waiting":
        state.reply_queue.put("__CANCELLED__")

    return {"status": "cancelled", "task_id": task_id}


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    state = get_task(task_id)
    if not state:
        raise gateway_error(ErrorCode.TASK_NOT_FOUND)

    return {
        "task_id": task_id,
        "status": state.status,
        "result": state.result,
        "token_totals": state.token_totals,
    }
