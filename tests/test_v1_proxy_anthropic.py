"""End-to-end tests for /anthropic/v1/messages Anthropic-native endpoint.

Uses TestClient with dependency_overrides to avoid real network calls.
Follows the same pattern as test_v1_admission.py.
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from hermit_agent.gateway import app
from hermit_agent.gateway.admission import AdmissionController, AdmissionDenied
from hermit_agent.gateway.providers import ProviderAdapter
from hermit_agent.gateway.routes import anthropic as anthropic_mod
from hermit_agent.gateway.routes import v1 as v1_mod


# ─── Test doubles ──────────────────────────────────────────────────────────


class _AlwaysDeny(AdmissionController):
    async def acquire(self, model: str):
        raise AdmissionDenied(
            f"ollama at capacity for '{model}'",
            retry_after=5,
        )


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


def _make_openai_sse_chunk(text: str, finish_reason=None) -> bytes:
    """Build a minimal OpenAI SSE data record."""
    choice: dict = {"delta": {"content": text}}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    data = json.dumps({"choices": [choice]})
    return f"data: {data}\n\n".encode()


class _StubAdapter(ProviderAdapter):
    """Deterministic adapter: captures call args, yields pre-set chunks."""

    def __init__(
        self,
        openai_chunks: list[bytes] | None = None,
        anthropic_chunks: list[bytes] | None = None,
        raise_before: bool = False,
    ):
        self.openai_chunks = openai_chunks or []
        self.anthropic_chunks = anthropic_chunks or [b'{"ok": true}']
        self.raise_before = raise_before
        self.captured_openai_body: dict | None = None
        self.captured_anthropic_body: dict | None = None
        self.captured_stream: bool | None = None

    async def forward_openai(self, req_body: dict, stream: bool) -> AsyncIterator[bytes]:
        self.captured_openai_body = req_body
        self.captured_stream = stream
        if self.raise_before:
            raise RuntimeError("adapter failed before yielding")
        for chunk in self.openai_chunks:
            yield chunk

    async def forward_anthropic(self, req_body: dict, stream: bool) -> AsyncIterator[bytes]:
        self.captured_anthropic_body = req_body
        self.captured_stream = stream
        for chunk in self.anthropic_chunks:
            yield chunk


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
    """Default: test key is allowed on every platform."""

    async def _allow_all(api_key: str) -> set[str]:
        return {"local", "z.ai", "anthropic", "codex"}

    monkeypatch.setattr(anthropic_mod, "allowed_platforms", _allow_all)


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset shared v1 caches between tests."""
    v1_mod._admission = None
    v1_mod._adapters.clear()
    yield
    v1_mod._admission = None
    v1_mod._adapters.clear()


def _install_stub_adapter(platform: str, adapter: ProviderAdapter) -> None:
    v1_mod._adapters[platform] = adapter


# ─── Tests ─────────────────────────────────────────────────────────────────


def test_zai_anthropic_passthrough_streaming():
    """z.ai: adapter.forward_anthropic chunks are yielded verbatim in the SSE stream."""
    v1_mod._admission = _AlwaysAdmit()
    chunks = [b"data: chunk1\n\n", b"data: chunk2\n\n", b"data: chunk3\n\n"]
    stub = _StubAdapter(anthropic_chunks=chunks)
    _install_stub_adapter("z.ai", stub)

    client = TestClient(app)
    with client.stream(
        "POST",
        "/anthropic/v1/messages",
        json={
            "model": "glm-5.1",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
    ) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        received = b"".join(r.iter_bytes())

    assert received == b"".join(chunks)
    assert stub.captured_anthropic_body is not None
    assert stub.captured_stream is True


def test_zai_anthropic_passthrough_non_streaming():
    """z.ai non-streaming: adapter yields full JSON; response body matches."""
    v1_mod._admission = _AlwaysAdmit()
    response_json = json.dumps({
        "id": "msg_abc",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "Hello!"}],
        "model": "glm-5.1",
        "stop_reason": "end_turn",
    }).encode()
    stub = _StubAdapter(anthropic_chunks=[response_json])
    _install_stub_adapter("z.ai", stub)

    client = TestClient(app)
    r = client.post(
        "/anthropic/v1/messages",
        json={
            "model": "glm-5.1",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False,
        },
    )
    assert r.status_code == 200
    assert r.content == response_json
    assert stub.captured_stream is False


def test_ollama_translated_path():
    """Local/ollama: OpenAI SSE input is translated to Anthropic SSE output."""
    v1_mod._admission = _AlwaysAdmit()
    openai_chunks = [
        _make_openai_sse_chunk("Hello"),
        _make_openai_sse_chunk(" world", finish_reason="stop"),
        b"data: [DONE]\n\n",
    ]
    stub = _StubAdapter(openai_chunks=openai_chunks)
    _install_stub_adapter("local", stub)

    client = TestClient(app)
    with client.stream(
        "POST",
        "/anthropic/v1/messages",
        json={
            "model": "qwen3-coder:30b",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        received = b"".join(r.iter_bytes())

    # Verify Anthropic SSE event structure is present.
    text = received.decode()
    assert "message_start" in text
    assert "content_block_start" in text
    assert "content_block_delta" in text
    assert "content_block_stop" in text
    assert "message_stop" in text
    # Text content should be preserved.
    assert "Hello" in text
    assert "world" in text


def test_local_tool_use_returns_400():
    """Body with non-text content block raises 400 unsupported_tool_translation."""
    v1_mod._admission = _AlwaysAdmit()
    stub = _StubAdapter()
    _install_stub_adapter("local", stub)

    client = TestClient(app)
    r = client.post(
        "/anthropic/v1/messages",
        json={
            "model": "llama3:8b",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "tool_use", "id": "t1", "name": "foo", "input": {}}],
                }
            ],
            "stream": False,
        },
    )
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["code"] == "unsupported_tool_translation"


def test_unknown_model_returns_400():
    """Model with no routing rule → 400 unknown_platform."""
    v1_mod._admission = _AlwaysAdmit()

    client = TestClient(app)
    r = client.post(
        "/anthropic/v1/messages",
        json={
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["code"] == "unknown_platform"
    assert "gpt-4" in body["detail"]["message"]


def test_forbidden_platform_returns_403(monkeypatch):
    """API key not authorized for platform → 403 forbidden_platform."""
    v1_mod._admission = _AlwaysAdmit()

    async def _local_only(api_key: str) -> set[str]:
        return {"local"}

    monkeypatch.setattr(anthropic_mod, "allowed_platforms", _local_only)

    client = TestClient(app)
    r = client.post(
        "/anthropic/v1/messages",
        json={
            "model": "glm-5.1",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 403
    body = r.json()
    assert body["detail"]["code"] == "forbidden_platform"
    assert "z.ai" in body["detail"]["message"]


def test_admission_denied_returns_503():
    """Admission controller denies → 503 with Retry-After header."""
    v1_mod._admission = _AlwaysDeny(ollama_max_loaded=1, external_max_concurrent=1)
    _install_stub_adapter("local", _StubAdapter())

    client = TestClient(app)
    r = client.post(
        "/anthropic/v1/messages",
        json={
            "model": "llama3:8b",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 503
    body = r.json()
    assert body["detail"]["code"] == "server_busy"
    assert r.headers.get("Retry-After") == "5"


def test_admission_token_released_on_tool_use_400():
    """Token is released even when UnsupportedToolTranslation causes a 400."""
    admit = _AlwaysAdmit()
    v1_mod._admission = admit
    stub = _StubAdapter()
    _install_stub_adapter("local", stub)

    client = TestClient(app)
    r = client.post(
        "/anthropic/v1/messages",
        json={
            "model": "llama3:8b",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "image", "source": {"type": "url", "url": "http://x"}}],
                }
            ],
            "stream": False,
        },
    )
    assert r.status_code == 400
    # Token must have been released even though we got 400.
    assert admit.released == 1
