"""Tests for ZaiAdapter provider."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hermit_agent.gateway.providers import ZaiAdapter


def _make_streaming_response(chunks: list[bytes]) -> MagicMock:
    mock_response = MagicMock()
    mock_response.status_code = 200

    async def _aiter_bytes():
        for chunk in chunks:
            yield chunk

    mock_response.aiter_bytes = _aiter_bytes
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)
    return mock_response


def _make_non_streaming_response(body: bytes) -> MagicMock:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = body
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)
    return mock_response


def test_forward_openai_streaming():
    """ZaiAdapter must pass Authorization: Bearer header and yield chunks verbatim."""
    chunks = [b"data: tok1\n\n", b"data: [DONE]\n\n"]
    mock_resp = _make_streaming_response(chunks)

    async def _run():
        adapter = ZaiAdapter(
            openai_base_url="https://api.z.ai/api/paas/v4",
            anthropic_base_url="https://api.z.ai/api/anthropic",
            api_key="test-key",
        )

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = MagicMock(return_value=mock_resp)

            collected = []
            async for chunk in adapter.forward_openai({"model": "glm-5.1"}, stream=True):
                collected.append(chunk)

        call_args = mock_client.stream.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "https://api.z.ai/api/paas/v4/chat/completions"
        headers = call_args[1].get("headers", {})
        assert headers.get("Authorization") == "Bearer test-key"
        assert collected == chunks

    asyncio.run(_run())


def test_forward_openai_non_streaming():
    """ZaiAdapter non-streaming openai: full body yielded once."""
    body = b'{"choices": [{"message": {"content": "hi"}}]}'
    mock_resp = _make_non_streaming_response(body)

    async def _run():
        adapter = ZaiAdapter(
            openai_base_url="https://api.z.ai/api/paas/v4",
            anthropic_base_url="https://api.z.ai/api/anthropic",
            api_key="test-key",
        )

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)

            collected = []
            async for chunk in adapter.forward_openai({"model": "glm-5.1"}, stream=False):
                collected.append(chunk)

        assert collected == [body]

    asyncio.run(_run())


def test_forward_anthropic_streaming():
    """ZaiAdapter must pass x-api-key + anthropic-version headers for Anthropic path."""
    chunks = [b"data: ev1\n\n", b"data: [DONE]\n\n"]
    mock_resp = _make_streaming_response(chunks)

    async def _run():
        adapter = ZaiAdapter(
            openai_base_url="https://api.z.ai/api/paas/v4",
            anthropic_base_url="https://api.z.ai/api/anthropic",
            api_key="test-key",
        )

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = MagicMock(return_value=mock_resp)

            collected = []
            async for chunk in adapter.forward_anthropic({"model": "claude-3-5-sonnet"}, stream=True):
                collected.append(chunk)

        call_args = mock_client.stream.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "https://api.z.ai/api/anthropic/v1/messages"
        headers = call_args[1].get("headers", {})
        assert headers.get("x-api-key") == "test-key"
        assert headers.get("anthropic-version") == "2023-06-01"
        assert collected == chunks

    asyncio.run(_run())


def test_forward_anthropic_non_streaming():
    """ZaiAdapter non-streaming anthropic: full body yielded once."""
    body = b'{"content": [{"text": "hello"}]}'
    mock_resp = _make_non_streaming_response(body)

    async def _run():
        adapter = ZaiAdapter(
            openai_base_url="https://api.z.ai/api/paas/v4",
            anthropic_base_url="https://api.z.ai/api/anthropic",
            api_key="test-key",
        )

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)

            collected = []
            async for chunk in adapter.forward_anthropic({"model": "claude-3-5-sonnet"}, stream=False):
                collected.append(chunk)

        assert collected == [body]

    asyncio.run(_run())
