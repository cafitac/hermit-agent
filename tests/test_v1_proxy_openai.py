"""Tests for /v1/chat/completions OpenAI-native proxy pass-through behavior.

Covers the raw-body forwarding contract: the handler must forward the full
OpenAI request payload verbatim (including unknown fields) to the chosen
provider adapter, and pipe the adapter's byte stream back to the caller
without transformation.
"""
from __future__ import annotations

from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from hermit_agent.gateway import app
from hermit_agent.gateway.admission import AdmissionController
from hermit_agent.gateway.providers import ProviderAdapter
from hermit_agent.gateway.routes import v1 as v1_mod


class _AlwaysAdmit(AdmissionController):
    def __init__(self):
        super().__init__(ollama_max_loaded=1, external_max_concurrent=1)
        self.released = 0

    async def acquire(self, model: str):
        outer = self

        class _Tok:
            def release(self_tok):
                outer.released += 1
        return _Tok()


class _RecordingAdapter(ProviderAdapter):
    """Adapter that records what it was called with and yields preset bytes."""

    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.captured_body: dict | None = None
        self.captured_stream: bool | None = None

    async def forward_openai(self, req_body: dict, stream: bool) -> AsyncIterator[bytes]:
        self.captured_body = req_body
        self.captured_stream = stream
        for chunk in self.chunks:
            yield chunk

    async def forward_anthropic(self, req_body: dict, stream: bool) -> AsyncIterator[bytes]:
        raise NotImplementedError
        yield  # type: ignore[unreachable]


# ─── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _bypass_auth():
    from hermit_agent.gateway.auth import AuthContext, get_current_user
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user="test-user", api_key="test-key"
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def _allow_all_platforms(monkeypatch):
    async def _allow_all(api_key: str) -> set[str]:
        return {"local", "z.ai", "anthropic", "codex"}
    monkeypatch.setattr(v1_mod, "allowed_platforms", _allow_all)


@pytest.fixture(autouse=True)
def _reset_state():
    v1_mod._admission = None
    v1_mod._adapters.clear()
    yield
    v1_mod._admission = None
    v1_mod._adapters.clear()


def _install(platform: str, adapter: ProviderAdapter) -> None:
    v1_mod._adapters[platform] = adapter


# ─── Tests ─────────────────────────────────────────────────────────────────

def test_ollama_streaming_passthrough():
    """Ollama-routed model streams bytes yielded by adapter verbatim."""
    v1_mod._admission = _AlwaysAdmit()
    chunks = [
        b'data: {"choices":[{"delta":{"content":"he"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]
    adapter = _RecordingAdapter(chunks=chunks)
    _install("local", adapter)

    client = TestClient(app)
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "qwen3-coder:30b",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as r:
        assert r.status_code == 200
        received = b"".join(r.iter_bytes())
    assert received == b"".join(chunks)
    assert adapter.captured_stream is True


def test_zai_streaming_passthrough():
    """z.ai-routed model (glm-*) streams bytes yielded by adapter verbatim."""
    v1_mod._admission = _AlwaysAdmit()
    chunks = [
        b'data: {"choices":[{"delta":{"content":"z1"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"z2"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]
    adapter = _RecordingAdapter(chunks=chunks)
    _install("z.ai", adapter)

    client = TestClient(app)
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "glm-5.1",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as r:
        assert r.status_code == 200
        received = b"".join(r.iter_bytes())
    assert received == b"".join(chunks)
    assert adapter.captured_stream is True


def test_non_streaming_aggregation():
    """Non-streaming path concatenates all adapter chunks into one response body."""
    v1_mod._admission = _AlwaysAdmit()
    chunks = [b'{"id": "cmpl-1",', b' "choices": []}']
    adapter = _RecordingAdapter(chunks=chunks)
    _install("local", adapter)

    client = TestClient(app)
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "llama3:8b",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )
    assert r.status_code == 200
    assert r.content == b"".join(chunks)
    assert adapter.captured_stream is False


def test_unknown_fields_passthrough():
    """Fields the gateway does not parse (tool_choice, response_format, …) reach the adapter intact."""
    v1_mod._admission = _AlwaysAdmit()
    adapter = _RecordingAdapter(chunks=[b'{"ok": true}'])
    _install("z.ai", adapter)

    payload = {
        "model": "glm-5.1",
        "messages": [{"role": "user", "content": "do the thing"}],
        "stream": False,
        "tool_choice": "auto",
        "response_format": {"type": "json_object"},
        "top_p": 0.7,
        "seed": 42,
        "logprobs": True,
    }
    client = TestClient(app)
    r = client.post("/v1/chat/completions", json=payload)
    assert r.status_code == 200
    assert adapter.captured_body == payload
    # Sanity: each extra field survived.
    assert adapter.captured_body["tool_choice"] == "auto"
    assert adapter.captured_body["response_format"] == {"type": "json_object"}
    assert adapter.captured_body["top_p"] == 0.7
    assert adapter.captured_body["seed"] == 42
    assert adapter.captured_body["logprobs"] is True


def test_zai_streaming_sse_format():
    """SSE framing (data: {...}\\n\\n) arrives intact across the proxy boundary."""
    v1_mod._admission = _AlwaysAdmit()
    # Canonical OpenAI SSE framing — each event is a single `data: {...}\n\n` frame.
    chunks = [
        b'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"role":"assistant"}}]}\n\n',
        b'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"content":"hi"}}]}\n\n',
        b'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n',
        b"data: [DONE]\n\n",
    ]
    adapter = _RecordingAdapter(chunks=chunks)
    _install("z.ai", adapter)

    client = TestClient(app)
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "glm-5.1",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as r:
        assert r.status_code == 200
        received = b"".join(r.iter_bytes())
    # Byte-for-byte preservation — no re-serialization.
    assert received == b"".join(chunks)
    # Each original frame still ends with the blank-line terminator.
    for frame in chunks:
        assert frame in received
        assert frame.endswith(b"\n\n")
