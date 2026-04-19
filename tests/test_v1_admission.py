"""End-to-end tests for /v1/chat/completions admission and ACL plumbing.

Runs the FastAPI app via TestClient and swaps the module-level admission
controller and adapter cache for deterministic test doubles.
"""
from __future__ import annotations

from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from hermit_agent.gateway import app
from hermit_agent.gateway.admission import AdmissionController, AdmissionDenied
from hermit_agent.gateway.providers import ProviderAdapter
from hermit_agent.gateway.routes import v1 as v1_mod


class _AlwaysDeny(AdmissionController):
    async def acquire(self, model: str):
        raise AdmissionDenied(
            f"ollama at capacity for '{model}'",
            retry_after=7,
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


class _StubAdapter(ProviderAdapter):
    """Deterministic adapter: captures body, yields pre-set chunks, optionally raises."""

    def __init__(
        self,
        chunks: list[bytes] | None = None,
        raise_after: int | None = None,
        raise_before: bool = False,
    ):
        self.chunks = chunks or [b'{"ok": true}']
        self.raise_after = raise_after
        self.raise_before = raise_before
        self.captured_body: dict | None = None
        self.captured_stream: bool | None = None

    async def forward_openai(self, req_body: dict, stream: bool) -> AsyncIterator[bytes]:
        self.captured_body = req_body
        self.captured_stream = stream
        if self.raise_before:
            raise RuntimeError("adapter failed before yielding")
        for idx, chunk in enumerate(self.chunks):
            if self.raise_after is not None and idx >= self.raise_after:
                raise RuntimeError(f"adapter failed mid-stream at chunk {idx}")
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
    """Default: test key is allowed on every platform."""
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


def _install_stub_adapter(platform: str, adapter: ProviderAdapter) -> None:
    v1_mod._adapters[platform] = adapter


# ─── Tests ─────────────────────────────────────────────────────────────────

def test_admission_denied_returns_503_with_retry_after():
    v1_mod._admission = _AlwaysDeny(ollama_max_loaded=1, external_max_concurrent=1)
    _install_stub_adapter("local", _StubAdapter())

    client = TestClient(app)
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "new-model:tag",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )
    assert r.status_code == 503
    body = r.json()
    assert body["detail"]["code"] == "server_busy"
    assert "capacity" in body["detail"]["message"].lower()
    assert r.headers.get("Retry-After") == "7"


def test_unknown_model_returns_400():
    v1_mod._admission = _AlwaysAdmit()

    client = TestClient(app)
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["code"] == "unknown_platform"
    assert "gpt-4" in body["detail"]["message"]


def test_forbidden_platform_returns_403(monkeypatch):
    v1_mod._admission = _AlwaysAdmit()

    async def _local_only(api_key: str) -> set[str]:
        return {"local"}
    monkeypatch.setattr(v1_mod, "allowed_platforms", _local_only)

    client = TestClient(app)
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "glm-5.1",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )
    assert r.status_code == 403
    body = r.json()
    assert body["detail"]["code"] == "forbidden_platform"
    assert "z.ai" in body["detail"]["message"]


def test_admission_token_released_on_success():
    admit = _AlwaysAdmit()
    v1_mod._admission = admit
    stub = _StubAdapter(chunks=[b'{"choices": []}'])
    _install_stub_adapter("local", stub)

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
    assert admit.released == 1


def test_admission_token_released_on_mid_stream_exception():
    admit = _AlwaysAdmit()
    v1_mod._admission = admit
    # Yields 1 chunk then raises on the 2nd.
    stub = _StubAdapter(chunks=[b"data: a\n\n", b"data: b\n\n"], raise_after=1)
    _install_stub_adapter("local", stub)

    client = TestClient(app)
    with pytest.raises(RuntimeError):
        # Streaming — raise propagates out of the generator consumed by TestClient.
        with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "llama3:8b",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        ) as r:
            for _ in r.iter_bytes():
                pass
    assert admit.released == 1


def test_admission_token_released_on_nonstreaming_exception():
    admit = _AlwaysAdmit()
    v1_mod._admission = admit
    stub = _StubAdapter(raise_before=True)
    _install_stub_adapter("local", stub)

    client = TestClient(app)
    with pytest.raises(RuntimeError):
        client.post(
            "/v1/chat/completions",
            json={
                "model": "llama3:8b",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
            },
        )
    assert admit.released == 1


def test_successful_proxy_forwards_body():
    admit = _AlwaysAdmit()
    v1_mod._admission = admit
    stub = _StubAdapter(chunks=[b'{"ok": true}'])
    _install_stub_adapter("local", stub)

    payload = {
        "model": "llama3:8b",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
        "tool_choice": "auto",
        "response_format": {"type": "json_object"},
    }
    client = TestClient(app)
    r = client.post("/v1/chat/completions", json=payload)
    assert r.status_code == 200
    # The adapter saw the raw dict, unmodified.
    assert stub.captured_body == payload
    assert stub.captured_stream is False
