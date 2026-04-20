"""Admission controller — ollama memory cap + external concurrency.

The gateway must refuse to load a new ollama model when the node is
already carrying `ollama_max_loaded` models (otherwise the next swap
blows memory). External providers (z.ai etc.) just queue — concurrency
is capped but excess requests wait instead of failing.
"""
from __future__ import annotations

import asyncio

import pytest

from hermit_agent.gateway.admission import AdmissionController, AdmissionDenied


def _fake_ps(loaded: set[str]):
    async def _factory():
        return set(loaded)
    return _factory


# ── Model routing ──────────────────────────────────────────────────────────

def test_is_ollama_model_detection():
    assert AdmissionController.is_ollama_model("qwen3-coder:30b") is True
    assert AdmissionController.is_ollama_model("llama3:8b") is True
    assert AdmissionController.is_ollama_model("glm-5.1") is False
    assert AdmissionController.is_ollama_model("gpt-4o") is False
    assert AdmissionController.is_ollama_model("") is False


# ── Ollama admission ───────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_admission_allows_already_loaded_model():
    ctl = AdmissionController(
        ollama_max_loaded=1,
        ps_client_factory=_fake_ps({"qwen3-coder:30b"}),
    )
    token = await ctl.acquire("qwen3-coder:30b")
    assert token is not None
    token.release()


@pytest.mark.anyio
async def test_admission_rejects_new_model_when_full():
    ctl = AdmissionController(
        ollama_max_loaded=1,
        ps_client_factory=_fake_ps({"qwen3-coder:30b"}),
    )
    with pytest.raises(AdmissionDenied) as exc:
        await ctl.acquire("llama3:8b")
    assert exc.value.retry_after >= 1
    assert "capacity" in str(exc.value).lower()


@pytest.mark.anyio
async def test_admission_allows_new_model_when_slot_free():
    ctl = AdmissionController(
        ollama_max_loaded=1,
        ps_client_factory=_fake_ps(set()),
    )
    token = await ctl.acquire("llama3:8b")
    token.release()


@pytest.mark.anyio
async def test_admission_allows_multiple_loaded_when_budget_permits():
    ctl = AdmissionController(
        ollama_max_loaded=2,
        ps_client_factory=_fake_ps({"a:1"}),
    )
    token = await ctl.acquire("b:2")
    token.release()


@pytest.mark.anyio
async def test_admission_fail_open_when_ps_errors():
    """If we cannot reach ollama /api/ps, err on the side of admitting.

    The alternative (blocking all traffic because health-check failed)
    would turn a transient ollama-side blip into a full gateway outage.
    """
    async def _broken_ps():
        raise RuntimeError("network down")
    ctl = AdmissionController(
        ollama_max_loaded=1,
        ps_client_factory=_broken_ps,
    )
    token = await ctl.acquire("qwen3-coder:30b")
    token.release()


@pytest.mark.anyio
async def test_token_release_frees_ollama_slot():
    ctl = AdmissionController(
        ollama_max_loaded=1,
        ps_client_factory=_fake_ps({"qwen3-coder:30b"}),
    )
    t1 = await ctl.acquire("qwen3-coder:30b")
    t1.release()
    # Second acquire of the same model must succeed immediately.
    t2 = await asyncio.wait_for(ctl.acquire("qwen3-coder:30b"), timeout=0.5)
    t2.release()


# ── External admission ────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_external_admission_queues_past_limit():
    """External providers queue. The N+1 request waits; it does not fail."""
    ctl = AdmissionController(
        ollama_max_loaded=1,
        external_max_concurrent=2,
    )
    t1 = await ctl.acquire("glm-5.1")
    t2 = await ctl.acquire("glm-5.1")
    # Third should block until t1 releases.
    third_task = asyncio.create_task(ctl.acquire("glm-5.1"))
    await asyncio.sleep(0.05)
    assert not third_task.done(), "third external request should be queued"
    t1.release()
    t3 = await asyncio.wait_for(third_task, timeout=0.5)
    t2.release()
    t3.release()


@pytest.mark.anyio
async def test_external_does_not_consume_ollama_budget():
    """An external call must not count against the ollama memory cap."""
    ctl = AdmissionController(
        ollama_max_loaded=1,
        external_max_concurrent=5,
        ps_client_factory=_fake_ps({"qwen3-coder:30b"}),
    )
    # Hold an ollama slot and a z.ai slot simultaneously.
    ollama_tok = await ctl.acquire("qwen3-coder:30b")
    ext_tok = await ctl.acquire("glm-5.1")
    ollama_tok.release()
    ext_tok.release()


# ── URL normalization ─────────────────────────────────────────────────────

def test_ollama_base_strips_trailing_v1():
    """Settings carry `ollama_url = http://host:11434/v1` for OpenAI compat,
    but /api/ps lives at the root. The controller must strip `/v1`."""
    ctl = AdmissionController(ollama_url="http://localhost:11434/v1")
    assert ctl._ollama_base == "http://localhost:11434"

    ctl2 = AdmissionController(ollama_url="http://localhost:11434/")
    assert ctl2._ollama_base == "http://localhost:11434"
