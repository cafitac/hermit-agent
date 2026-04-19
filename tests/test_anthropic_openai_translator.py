"""Anthropic <-> OpenAI translator — request shape + SSE stream framing.

The translator is a standalone utility used by the Anthropic-native endpoint
(US-006) when the resolved platform only speaks OpenAI wire format (ollama).
Text-only in v1 — tool_use / tool_result / image blocks raise
UnsupportedToolTranslation, which the route layer maps to HTTP 400.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

import pytest

from hermit_agent.gateway.providers.anthropic_translator import (
    UnsupportedToolTranslation,
    openai_stream_to_anthropic,
    request_to_openai,
)


# ── request_to_openai ─────────────────────────────────────────────────────


def test_request_top_level_system_string():
    """Top-level string `system` becomes the first message with role=system."""
    anthropic_body = {
        "model": "qwen3-coder:30b",
        "system": "You are a helpful assistant.",
        "messages": [{"role": "user", "content": "hi"}],
    }
    openai = request_to_openai(anthropic_body)
    assert openai["messages"][0] == {
        "role": "system",
        "content": "You are a helpful assistant.",
    }
    assert openai["messages"][1] == {"role": "user", "content": "hi"}


def test_request_system_list_of_text_blocks():
    """List-of-blocks `system` is concatenated into a single string."""
    anthropic_body = {
        "model": "qwen3-coder:30b",
        "system": [
            {"type": "text", "text": "a"},
            {"type": "text", "text": "b"},
        ],
        "messages": [{"role": "user", "content": "hi"}],
    }
    openai = request_to_openai(anthropic_body)
    assert openai["messages"][0] == {"role": "system", "content": "ab"}


def test_request_message_content_list_text_blocks_concatenated():
    """Message content list of text blocks concatenates into one string."""
    anthropic_body = {
        "model": "qwen3-coder:30b",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "a"},
                    {"type": "text", "text": "b"},
                ],
            }
        ],
    }
    openai = request_to_openai(anthropic_body)
    assert openai["messages"] == [{"role": "user", "content": "ab"}]


def test_request_string_content_preserved():
    """Plain string content is kept verbatim."""
    anthropic_body = {
        "model": "qwen3-coder:30b",
        "messages": [{"role": "user", "content": "plain string"}],
    }
    openai = request_to_openai(anthropic_body)
    assert openai["messages"] == [{"role": "user", "content": "plain string"}]


def test_request_tool_use_raises():
    anthropic_body = {
        "model": "qwen3-coder:30b",
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "bash", "input": {}}
                ],
            }
        ],
    }
    with pytest.raises(UnsupportedToolTranslation):
        request_to_openai(anthropic_body)


def test_request_tool_result_raises():
    anthropic_body = {
        "model": "qwen3-coder:30b",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}
                ],
            }
        ],
    }
    with pytest.raises(UnsupportedToolTranslation):
        request_to_openai(anthropic_body)


def test_request_image_block_raises():
    """Image blocks are not supported in v1 (text-only translator)."""
    anthropic_body = {
        "model": "qwen3-coder:30b",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "data": "xxx"}}
                ],
            }
        ],
    }
    with pytest.raises(UnsupportedToolTranslation):
        request_to_openai(anthropic_body)


def test_request_preserves_max_tokens_and_stream():
    anthropic_body = {
        "model": "qwen3-coder:30b",
        "max_tokens": 1024,
        "stream": True,
        "temperature": 0.5,
        "top_p": 0.9,
        "messages": [{"role": "user", "content": "hi"}],
    }
    openai = request_to_openai(anthropic_body)
    assert openai["model"] == "qwen3-coder:30b"
    assert openai["max_tokens"] == 1024
    assert openai["stream"] is True
    assert openai["temperature"] == 0.5
    assert openai["top_p"] == 0.9


def test_request_stop_sequences_mapped_to_stop():
    """Anthropic `stop_sequences` is renamed to OpenAI `stop`."""
    anthropic_body = {
        "model": "qwen3-coder:30b",
        "stop_sequences": ["###", "END"],
        "messages": [{"role": "user", "content": "hi"}],
    }
    openai = request_to_openai(anthropic_body)
    assert openai["stop"] == ["###", "END"]
    assert "stop_sequences" not in openai


# ── openai_stream_to_anthropic ────────────────────────────────────────────


def _make_openai_chunks(chunks: list[bytes]):
    """Wrap a list of byte chunks as an AsyncIterator[bytes]."""
    async def _aiter() -> AsyncIterator[bytes]:
        for c in chunks:
            yield c
    return _aiter()


def _collect_events(aiter: AsyncIterator[bytes]) -> list[tuple[str, dict]]:
    """Drain an SSE byte stream; return list of (event_name, data_dict)."""
    async def _run():
        raw = b""
        async for chunk in aiter:
            raw += chunk
        return raw

    raw = asyncio.run(_run())
    # Split SSE records.
    events: list[tuple[str, dict]] = []
    for record in raw.split(b"\n\n"):
        record = record.strip()
        if not record:
            continue
        event_name: str | None = None
        data_obj: dict | None = None
        for line in record.split(b"\n"):
            if line.startswith(b"event:"):
                event_name = line[len(b"event:"):].strip().decode("utf-8")
            elif line.startswith(b"data:"):
                payload = line[len(b"data:"):].strip()
                data_obj = json.loads(payload)
        if event_name is not None and data_obj is not None:
            events.append((event_name, data_obj))
    return events


def _openai_line(obj: dict) -> bytes:
    return b"data: " + json.dumps(obj).encode("utf-8") + b"\n\n"


def test_sse_framing_correctness():
    """Full event sequence: message_start, content_block_start,
    content_block_delta (x2), content_block_stop, message_delta, message_stop.
    """
    role_chunk = _openai_line({
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}],
    })
    delta1 = _openai_line({
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {"content": "Hello"}}],
    })
    delta2 = _openai_line({
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {"content": " world"}}],
    })
    finish = _openai_line({
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    })
    done = b"data: [DONE]\n\n"

    src = _make_openai_chunks([role_chunk, delta1, delta2, finish, done])
    out = openai_stream_to_anthropic(src, model="qwen3-coder:30b")
    events = _collect_events(out)

    names = [name for name, _ in events]
    assert names == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]

    # Validate shape of message_start.
    _, msg_start = events[0]
    assert msg_start["type"] == "message_start"
    assert msg_start["message"]["model"] == "qwen3-coder:30b"
    assert msg_start["message"]["role"] == "assistant"
    assert msg_start["message"]["id"].startswith("msg_")

    # Validate content_block_start shape.
    _, block_start = events[1]
    assert block_start["content_block"] == {"type": "text", "text": ""}

    # Validate text deltas.
    assert events[2][1]["delta"] == {"type": "text_delta", "text": "Hello"}
    assert events[3][1]["delta"] == {"type": "text_delta", "text": " world"}

    # Validate message_delta stop_reason mapping.
    _, msg_delta = events[5]
    assert msg_delta["delta"]["stop_reason"] == "end_turn"


def test_stop_reason_mapping_length_to_max_tokens():
    role_chunk = _openai_line({
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}],
    })
    delta = _openai_line({
        "choices": [{"index": 0, "delta": {"content": "x"}}],
    })
    finish = _openai_line({
        "choices": [{"index": 0, "delta": {}, "finish_reason": "length"}],
    })
    src = _make_openai_chunks([role_chunk, delta, finish, b"data: [DONE]\n\n"])
    events = _collect_events(openai_stream_to_anthropic(src, model="m"))
    by_name = {name: data for name, data in events}
    assert by_name["message_delta"]["delta"]["stop_reason"] == "max_tokens"


def test_stop_reason_mapping_stop_to_end_turn():
    role_chunk = _openai_line({
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}],
    })
    delta = _openai_line({
        "choices": [{"index": 0, "delta": {"content": "x"}}],
    })
    finish = _openai_line({
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    })
    src = _make_openai_chunks([role_chunk, delta, finish, b"data: [DONE]\n\n"])
    events = _collect_events(openai_stream_to_anthropic(src, model="m"))
    by_name = {name: data for name, data in events}
    assert by_name["message_delta"]["delta"]["stop_reason"] == "end_turn"


def test_stop_reason_default_end_turn():
    """No finish_reason observed → default to end_turn."""
    role_chunk = _openai_line({
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}],
    })
    delta = _openai_line({
        "choices": [{"index": 0, "delta": {"content": "x"}}],
    })
    src = _make_openai_chunks([role_chunk, delta, b"data: [DONE]\n\n"])
    events = _collect_events(openai_stream_to_anthropic(src, model="m"))
    by_name = {name: data for name, data in events}
    assert by_name["message_delta"]["delta"]["stop_reason"] == "end_turn"


def test_text_round_trip():
    """Concatenated text from deltas equals the original string."""
    pieces = ["Hel", "lo", " ", "wor", "ld"]
    chunks = [_openai_line({
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}],
    })]
    for p in pieces:
        chunks.append(_openai_line({
            "choices": [{"index": 0, "delta": {"content": p}}],
        }))
    chunks.append(_openai_line({
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }))
    chunks.append(b"data: [DONE]\n\n")

    events = _collect_events(
        openai_stream_to_anthropic(_make_openai_chunks(chunks), model="m")
    )
    text = "".join(
        data["delta"]["text"]
        for name, data in events
        if name == "content_block_delta"
    )
    assert text == "Hello world"


def test_multi_chunk_sse_record_boundary():
    """A single SSE record may be split across multiple network chunks;
    the translator must buffer correctly and still parse the record.
    """
    role_chunk = _openai_line({
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}],
    })
    # Build a single delta record and bisect it mid-record.
    delta = _openai_line({
        "choices": [{"index": 0, "delta": {"content": "Hello"}}],
    })
    half = len(delta) // 2
    part_a = delta[:half]
    part_b = delta[half:]

    finish = _openai_line({
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    })
    done = b"data: [DONE]\n\n"

    src = _make_openai_chunks([role_chunk, part_a, part_b, finish, done])
    events = _collect_events(openai_stream_to_anthropic(src, model="m"))
    deltas = [data for name, data in events if name == "content_block_delta"]
    assert len(deltas) == 1
    assert deltas[0]["delta"]["text"] == "Hello"
