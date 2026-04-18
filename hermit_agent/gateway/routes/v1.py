from __future__ import annotations
import asyncio
import concurrent.futures
import json
import logging
import os
import time
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..auth import get_current_user
from ..errors import ErrorCode, gateway_error
from .._singletons import MAX_WORKERS

logger = logging.getLogger("hermit_agent.gateway.routes.v1")
router = APIRouter()

_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=MAX_WORKERS,
    thread_name_prefix="gateway-v1",
)



class ChatMessage(BaseModel):
    role: str  # "system" | "user" | "assistant"
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = ""
    messages: list[ChatMessage]
    stream: bool = False
    max_tokens: int | None = None
    temperature: float = 0.0



def _run_agent_sync(
    messages: list[dict],
    model: str,
    temperature: float,
    max_turns: int,
) -> dict:
    """Run AgentLoop in normal mode (no queues). Returns final response text and usage."""
    from ...llm_client import create_llm_client
    from ...loop import AgentLoop
    from ...permissions import PermissionMode
    from ...config import load_settings

    cfg = load_settings()
    llm_url = cfg.get("llm_url", "http://localhost:11434/v1")
    api_key = cfg.get("llm_api_key", "")
    llm = create_llm_client(base_url=llm_url, model=model, api_key=api_key)

    # Separate system from user/assistant in messages
    system_msg = None
    conversation: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        else:
            conversation.append({"role": m["role"], "content": m["content"]})

    # Split: last message as prompt, the rest as history
    prompt = ""
    history: list[dict] = []
    if conversation:
        *history, last = conversation
        prompt = last["content"]

    agent = AgentLoop(
        llm=llm,
        cwd=os.getcwd(),
        permission_mode=PermissionMode.ALLOW_READ,
        max_turns=max_turns,
        seed_handoff=cfg.get("seed_handoff", True),
        auto_wrap=cfg.get("auto_wrap", True),
    )
    if system_msg:
        agent.system_prompt = system_msg

    # Inject previous conversation history
    for msg in history:
        agent.messages.append(msg)

    result_text = agent.run(prompt) or ""

    return {
        "content": result_text,
        "usage": agent.token_totals,
        "model": model,
    }



@router.get("/models")
async def list_models(user: str = Depends(get_current_user)):
    from ...config import load_settings
    cfg = load_settings()
    model_id = cfg.get("model", "hermit_agent")
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "hermit_agent",
            }
        ],
    }


@router.post("/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    user: str = Depends(get_current_user),
):
    from ...config import load_settings
    cfg = load_settings()
    model = req.model or cfg.get("model", "hermit_agent")
    max_turns = min(req.max_tokens or 200, 500) if req.max_tokens else 200
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created_ts = int(time.time())

    messages = [m.model_dump() for m in req.messages]

    if req.stream:
        return StreamingResponse(
            _stream_response(
                completion_id=completion_id,
                created_ts=created_ts,
                model=model,
                messages=messages,
                max_turns=max_turns,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    # non-streaming
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _EXECUTOR,
        _run_agent_sync,
        messages, model, req.temperature, max_turns,
    )

    content = result["content"]
    usage = result["usage"]

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created_ts,
        "model": result["model"],
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
        },
    }


async def _stream_response(
    completion_id: str,
    created_ts: int,
    model: str,
    messages: list[dict],
    max_turns: int,
) -> AsyncGenerator[str, None]:
    """OpenAI-format SSE streaming. Runs AgentLoop in executor and splits the result into chunks."""
    loop = asyncio.get_running_loop()

    try:
        result = await loop.run_in_executor(
            _EXECUTOR,
            _run_agent_sync,
            messages, model, 0.0, max_turns,
        )
        content = result["content"]
        usage = result["usage"]
    except Exception:
        logger.exception("v1 stream failed")
        err_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created_ts,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(err_chunk)}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Role chunk
    role_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created_ts,
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
    }
    yield f"data: {json.dumps(role_chunk)}\n\n"

    # Split content into 50-char chunks (streaming simulation)
    chunk_size = 50
    for i in range(0, max(len(content), 1), chunk_size):
        piece = content[i:i + chunk_size]
        content_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created_ts,
            "model": model,
            "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(content_chunk)}\n\n"

    # Finish chunk (includes usage)
    finish_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created_ts,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
        },
    }
    yield f"data: {json.dumps(finish_chunk)}\n\n"
    yield "data: [DONE]\n\n"
