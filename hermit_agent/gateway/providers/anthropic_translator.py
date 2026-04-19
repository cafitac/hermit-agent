"""Anthropic <-> OpenAI wire-format translator for the gateway.

Used by the Anthropic-native endpoint when the resolved platform only speaks
OpenAI wire format (ollama in v1). ``tool_use``, ``tool_result``, and ``image``
blocks raise ``UnsupportedToolTranslation`` (callers map to HTTP 400).
"""
from __future__ import annotations

import json
import uuid
from typing import AsyncIterator


class UnsupportedToolTranslation(Exception):
    """Raised when the Anthropic request contains content blocks the v1
    translator cannot represent in OpenAI wire format (tool_use, tool_result,
    image, etc.). Route layer maps this to HTTP 400.
    """


# ── request translation ───────────────────────────────────────────────────


def _flatten_text_blocks(blocks: list, *, origin: str) -> str:
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            raise UnsupportedToolTranslation(
                f"unsupported {origin} block (not a dict): {block!r}"
            )
        btype = block.get("type")
        if btype != "text":
            raise UnsupportedToolTranslation(
                f"unsupported {origin} content block type: {btype!r}"
            )
        parts.append(block.get("text", ""))
    return "".join(parts)


def request_to_openai(anthropic_body: dict) -> dict:
    """Translate an Anthropic ``/v1/messages`` body to OpenAI ``/v1/chat/completions`` shape.

    Raises ``UnsupportedToolTranslation`` on any non-text content block.
    """
    openai: dict = {}

    for key in ("model", "max_tokens", "stream", "temperature", "top_p"):
        if key in anthropic_body:
            openai[key] = anthropic_body[key]

    if "stop_sequences" in anthropic_body:
        openai["stop"] = anthropic_body["stop_sequences"]

    messages: list[dict] = []

    system = anthropic_body.get("system")
    if system is not None:
        if isinstance(system, str):
            if system:
                messages.append({"role": "system", "content": system})
        elif isinstance(system, list):
            text = _flatten_text_blocks(system, origin="system")
            if text:
                messages.append({"role": "system", "content": text})
        else:
            raise UnsupportedToolTranslation(
                f"unsupported system field type: {type(system).__name__}"
            )

    for msg in anthropic_body.get("messages", []):
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
        elif isinstance(content, list):
            text = _flatten_text_blocks(content, origin="message")
            messages.append({"role": role, "content": text})
        else:
            raise UnsupportedToolTranslation(
                f"unsupported message content: {content!r}"
            )

    openai["messages"] = messages
    return openai


# ── streaming translation ─────────────────────────────────────────────────


_STOP_REASON_MAP = {
    "stop": "end_turn",
    "length": "max_tokens",
}


def _map_stop_reason(finish_reason: str | None) -> str:
    if finish_reason is None:
        return "end_turn"
    return _STOP_REASON_MAP.get(finish_reason, "end_turn")


def _sse_event(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


async def openai_stream_to_anthropic(
    openai_chunks: AsyncIterator[bytes],
    model: str,
) -> AsyncIterator[bytes]:
    """Translate an OpenAI SSE byte stream into an Anthropic SSE byte stream.

    Buffers until ``\\n\\n`` record separator; emits message_start →
    content_block_start → content_block_delta* → content_block_stop →
    message_delta → message_stop.
    """
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"
    started = False
    block_open = False
    finish_reason: str | None = None

    buffer = b""

    async for chunk in openai_chunks:
        buffer += chunk
        while b"\n\n" in buffer:
            record, buffer = buffer.split(b"\n\n", 1)
            # A record may contain multiple lines; only "data:" lines matter.
            for line in record.split(b"\n"):
                stripped = line.strip()
                if not stripped.startswith(b"data:"):
                    continue
                payload = stripped[len(b"data:"):].strip()
                if payload == b"[DONE]":
                    continue
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    # Malformed chunk — skip rather than abort the stream.
                    continue

                choices = data.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta") or {}
                fr = choice.get("finish_reason")
                if fr is not None:
                    finish_reason = fr

                if not started:
                    started = True
                    yield _sse_event("message_start", {
                        "type": "message_start",
                        "message": {
                            "id": msg_id,
                            "type": "message",
                            "role": "assistant",
                            "content": [],
                            "model": model,
                            "stop_reason": None,
                            "stop_sequence": None,
                            "usage": {"input_tokens": 0, "output_tokens": 0},
                        },
                    })

                if not block_open:
                    block_open = True
                    yield _sse_event("content_block_start", {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": ""},
                    })

                text = delta.get("content")
                if text:
                    yield _sse_event("content_block_delta", {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": text},
                    })

    if block_open:
        yield _sse_event(
            "content_block_stop",
            {"type": "content_block_stop", "index": 0},
        )
    if started:
        yield _sse_event("message_delta", {
            "type": "message_delta",
            "delta": {
                "stop_reason": _map_stop_reason(finish_reason),
                "stop_sequence": None,
            },
            "usage": {"output_tokens": 0},
        })
        yield _sse_event("message_stop", {"type": "message_stop"})
