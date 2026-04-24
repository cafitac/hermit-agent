"""Test LLM client retry/timeout policy.

- Default values: MAX_RETRIES=3, CALL_TIMEOUT=120.0
- 429 retries use flat delay — no exponential backoff
- Prioritize Retry-After header value if present
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import pytest

from hermit_agent.llm_client import LLMClientBase, _with_retry


def test_default_max_retries_is_three():
    assert LLMClientBase.MAX_RETRIES == 3


def test_default_call_timeout_is_120s():
    assert LLMClientBase.CALL_TIMEOUT == 120.0


def _make_429_response(retry_after: str | None = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after else {}
    request = httpx.Request("POST", "http://example/chat")
    return httpx.Response(status_code=429, headers=headers, request=request)


def test_429_retry_uses_flat_delay(monkeypatch):
    """429 retries must use the same delay regardless of the attempt count."""
    sleeps: list[float] = []
    monkeypatch.setattr("hermit_agent.llm_client._time.sleep", lambda s: sleeps.append(s))

    attempts = {"n": 0}

    def always_429():
        attempts["n"] += 1
        raise httpx.HTTPStatusError(
            "429", request=httpx.Request("POST", "http://x"), response=_make_429_response()
        )

    with pytest.raises(httpx.HTTPStatusError):
        _with_retry(always_429, max_retries=3)

    # max_retries=3 → 3 retries → 3 sleeps
    assert len(sleeps) == 3
    # All sleeps must be identical (flat) — no exponential backoff
    assert sleeps[0] == sleeps[1] == sleeps[2]
    # Reasonably short delay (5 seconds or less)
    assert all(s <= 5.0 for s in sleeps)


def test_429_respects_retry_after_header(monkeypatch):
    """If the Retry-After header is present, its value (in seconds) must be used."""
    sleeps: list[float] = []
    monkeypatch.setattr("hermit_agent.llm_client._time.sleep", lambda s: sleeps.append(s))

    def always_429_with_hint():
        raise httpx.HTTPStatusError(
            "429",
            request=httpx.Request("POST", "http://x"),
            response=_make_429_response(retry_after="7"),
        )

    with pytest.raises(httpx.HTTPStatusError):
        _with_retry(always_429_with_hint, max_retries=2)

    assert sleeps == [7.0, 7.0]


def test_total_wait_is_bounded(monkeypatch):
    """Under the default policy, the total wait time for infinite 429 retries must be 30 seconds or less."""
    sleeps: list[float] = []
    monkeypatch.setattr("hermit_agent.llm_client._time.sleep", lambda s: sleeps.append(s))

    def always_429():
        raise httpx.HTTPStatusError(
            "429", request=httpx.Request("POST", "http://x"), response=_make_429_response()
        )

    with pytest.raises(httpx.HTTPStatusError):
        _with_retry(always_429, max_retries=LLMClientBase.MAX_RETRIES)

    assert sum(sleeps) <= 30.0, f"total wait {sum(sleeps):.1f}s exceeds 30s budget"
