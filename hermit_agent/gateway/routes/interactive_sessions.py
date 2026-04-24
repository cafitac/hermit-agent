from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .._singletons import sse_manager
from ..auth import AuthContext, get_current_user
from ..errors import ErrorCode, gateway_error
from ..interactive_session_runtime import (
    cancel_interactive_session,
    create_interactive_session_runtime,
    get_interactive_session,
    load_interactive_session_runtime,
    reply_to_interactive_session,
    submit_interactive_turn,
)
from ...interactive_prompts import waiting_prompt_snapshot
from ..task_models import normalize_requested_model, normalize_task_cwd

router = APIRouter(prefix="/internal/interactive-sessions")


class InteractiveSessionRequest(BaseModel):
    cwd: str = ""
    model: str = ""
    parent_session_id: str | None = None
    session_id: str | None = None


class InteractiveMessageRequest(BaseModel):
    message: str


def _create_interactive_runtime_for_request(req: InteractiveSessionRequest):
    from ...config import get_primary_model, load_settings, select_llm_endpoint
    from ...llm_client import create_llm_client

    cwd = normalize_task_cwd(req.cwd)
    requested_model = normalize_requested_model(req.model)
    cfg = load_settings(cwd=cwd)
    selected_model = (
        get_primary_model(cfg, available_only=True) or get_primary_model(cfg)
        if requested_model == "__auto__"
        else requested_model
    )
    llm_url, api_key = select_llm_endpoint(selected_model, cfg)
    if not llm_url:
        raise gateway_error(ErrorCode.INVALID_REQUEST, f"Requested model unavailable: {selected_model}")
    llm = create_llm_client(base_url=llm_url, model=selected_model, api_key=api_key)

    existing = get_interactive_session(req.session_id or "") if req.session_id else None
    if existing is not None:
        return existing
    if req.session_id:
        try:
            return load_interactive_session_runtime(
                session_id=req.session_id,
                cwd=cwd,
                llm=llm,
            )
        except FileNotFoundError:
            pass
    return create_interactive_session_runtime(
        session_id=req.session_id,
        cwd=cwd,
        llm=llm,
        parent_session_id=req.parent_session_id,
    )


@router.post("")
async def create_interactive_session_endpoint(
    req: InteractiveSessionRequest,
    auth: AuthContext = Depends(get_current_user),
):
    runtime = _create_interactive_runtime_for_request(req)
    return {
        "session_id": runtime.session_id,
        "status": runtime.status,
        "mode": "interactive",
    }


@router.post("/{session_id}/messages")
async def send_interactive_message(
    session_id: str,
    req: InteractiveMessageRequest,
    auth: AuthContext = Depends(get_current_user),
):
    runtime = get_interactive_session(session_id)
    if runtime is None:
        raise gateway_error(ErrorCode.TASK_NOT_FOUND, f"Interactive session not found: {session_id}")
    if not req.message.strip():
        raise gateway_error(ErrorCode.INVALID_REQUEST, "message must not be empty")
    status = submit_interactive_turn(runtime, req.message)
    return {"session_id": session_id, "status": status}


@router.get("/{session_id}")
async def get_interactive_session_status(
    session_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    runtime = get_interactive_session(session_id)
    if runtime is None:
        raise gateway_error(ErrorCode.TASK_NOT_FOUND, f"Interactive session not found: {session_id}")
    waiting_prompt = None
    waiting_kind = None
    if runtime.waiting_prompt is not None:
        waiting_prompt = waiting_prompt_snapshot(runtime.waiting_prompt)
        waiting_kind = runtime.waiting_prompt.prompt_kind
    return {
        "session_id": session_id,
        "status": runtime.status,
        "parent_session_id": runtime.parent_session_id,
        "waiting_kind": waiting_kind,
        "waiting_prompt": waiting_prompt,
    }


@router.get("/{session_id}/stream")
async def stream_interactive_session(
    session_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    runtime = get_interactive_session(session_id)
    if runtime is None:
        raise gateway_error(ErrorCode.TASK_NOT_FOUND, f"Interactive session not found: {session_id}")
    return StreamingResponse(
        sse_manager.stream(session_id),
        media_type="text/event-stream",
        headers={
            "X-Session-ID": session_id,
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/{session_id}/reply")
async def reply_interactive_session(
    session_id: str,
    req: InteractiveMessageRequest,
    auth: AuthContext = Depends(get_current_user),
):
    runtime = get_interactive_session(session_id)
    if runtime is None:
        raise gateway_error(ErrorCode.TASK_NOT_FOUND, f"Interactive session not found: {session_id}")
    try:
        reply_to_interactive_session(runtime, req.message)
    except RuntimeError as exc:
        raise gateway_error(ErrorCode.TASK_ALREADY_DONE, str(exc))
    return {"status": "ok", "session_id": session_id}


@router.delete("/{session_id}")
async def delete_interactive_session_endpoint(
    session_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    runtime = get_interactive_session(session_id)
    if runtime is None:
        raise gateway_error(ErrorCode.TASK_NOT_FOUND, f"Interactive session not found: {session_id}")
    cancel_interactive_session(runtime)
    return {"status": "cancelled", "session_id": session_id}
