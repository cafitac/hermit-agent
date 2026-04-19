"""Anthropic-native proxy endpoint: POST /anthropic/v1/messages.

Route logic mirrors routes/v1.py but accepts and emits Anthropic wire format.
For z.ai (or future native Anthropic platforms) the body is forwarded verbatim
via adapter.forward_anthropic. For the local platform (ollama) the body is
translated to OpenAI format first via anthropic_translator, then the OpenAI
SSE stream is translated back to Anthropic SSE.
"""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from ..admission import AdmissionDenied
from ..auth import AuthContext, get_current_user
from ..db import allowed_platforms
from ..providers.anthropic_translator import (
    UnsupportedToolTranslation,
    openai_stream_to_anthropic,
    request_to_openai,
)
from ..routing import UnknownPlatform, resolve_platform
from .v1 import _get_admission, _get_adapter

logger = logging.getLogger("hermit_agent.gateway.routes.anthropic")
router = APIRouter()


def _build_anthropic_message(text: str, model: str) -> bytes:
    """Build a minimal Anthropic messages response JSON envelope."""
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"
    payload = {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": model,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }
    return json.dumps(payload).encode("utf-8")


async def _aggregate_openai_to_anthropic_text(openai_chunks, model: str) -> bytes:
    """Force-stream ollama, aggregate all text deltas, return Anthropic JSON envelope."""
    collected: list[str] = []
    async for sse_bytes in openai_stream_to_anthropic(openai_chunks, model=model):
        # sse_bytes is b"event: <name>\ndata: <json>\n\n"
        for line in sse_bytes.split(b"\n"):
            stripped = line.strip()
            if not stripped.startswith(b"data:"):
                continue
            payload = stripped[len(b"data:"):].strip()
            try:
                evt = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                continue
            if evt.get("type") == "content_block_delta":
                delta = evt.get("delta", {})
                if delta.get("type") == "text_delta":
                    collected.append(delta.get("text", ""))
    return _build_anthropic_message("".join(collected), model)


@router.post("/v1/messages")
async def messages(
    request: Request,
    auth: AuthContext = Depends(get_current_user),
):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_request",
                "message": "request body must be a JSON object",
                "type": "gateway_error",
            },
        )

    model = body.get("model") or ""
    if not model:
        from ...config import load_settings
        model = load_settings().get("model", "")

    try:
        platform = resolve_platform(model)
    except UnknownPlatform:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unknown_platform",
                "message": f"no route for model '{model}'",
                "type": "gateway_error",
            },
        )

    allowed = await allowed_platforms(auth.api_key)
    if platform not in allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "forbidden_platform",
                "message": f"key not authorized for platform '{platform}'",
                "type": "gateway_error",
            },
        )

    try:
        token = await _get_admission().acquire(model)
    except AdmissionDenied as denied:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "server_busy",
                "message": str(denied),
                "type": "gateway_error",
            },
            headers={"Retry-After": str(denied.retry_after)},
        )

    adapter = _get_adapter(platform)
    stream = bool(body.get("stream", False))

    if platform == "local":
        # Translate Anthropic body -> OpenAI, forward through ollama, translate back.
        try:
            openai_body = request_to_openai(body)
        except UnsupportedToolTranslation as exc:
            token.release()
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "unsupported_tool_translation",
                    "message": str(exc),
                    "type": "gateway_error",
                },
            )

        if stream:
            async def _gen_local_stream():
                try:
                    openai_chunks = adapter.forward_openai(openai_body, stream=True)
                    async for evt in openai_stream_to_anthropic(openai_chunks, model=model):
                        yield evt
                finally:
                    token.release()

            return StreamingResponse(
                _gen_local_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        # Non-streaming local: force stream=True on ollama, aggregate, build envelope.
        try:
            openai_chunks = adapter.forward_openai(openai_body, stream=True)
            body_bytes = await _aggregate_openai_to_anthropic_text(openai_chunks, model)
        finally:
            token.release()
        return Response(content=body_bytes, media_type="application/json")

    else:
        # Native Anthropic passthrough (z.ai or future providers).
        if stream:
            async def _gen_native_stream():
                try:
                    async for chunk in adapter.forward_anthropic(body, stream=True):
                        yield chunk
                finally:
                    token.release()

            return StreamingResponse(
                _gen_native_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        try:
            body_bytes = b""
            async for chunk in adapter.forward_anthropic(body, stream=False):
                body_bytes += chunk
        finally:
            token.release()
        return Response(content=body_bytes, media_type="application/json")
