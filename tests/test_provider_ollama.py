"""Tests for OllamaAdapter provider."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hermit_agent.gateway.providers import OllamaAdapter


def _make_streaming_response(chunks: list[bytes]) -> MagicMock:
    """Build a mock httpx streaming response that yields the given chunks."""
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
    """Adapter must POST to /chat/completions and yield SSE chunks verbatim."""
    chunks = [b"data: chunk1\n\n", b"data: chunk2\n\n", b"data: [DONE]\n\n"]
    mock_resp = _make_streaming_response(chunks)

    async def _run():
        adapter = OllamaAdapter(base_url="http://localhost:11434/v1")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = MagicMock(return_value=mock_resp)

            collected = []
            async for chunk in adapter.forward_openai({"model": "llama3"}, stream=True):
                collected.append(chunk)

        # Assert correct URL was called
        call_args = mock_client.stream.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "http://localhost:11434/v1/chat/completions"

        # Assert chunks are passed through verbatim
        assert collected == chunks

    asyncio.run(_run())


def test_forward_openai_non_streaming():
    """Non-streaming: full response body yielded exactly once."""
    body = b'{"id": "cmpl-1", "choices": [{"message": {"content": "hello"}}]}'
    mock_resp = _make_non_streaming_response(body)

    async def _run():
        adapter = OllamaAdapter(base_url="http://localhost:11434/v1")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)

            collected = []
            async for chunk in adapter.forward_openai({"model": "llama3"}, stream=False):
                collected.append(chunk)

        assert collected == [body]

    asyncio.run(_run())


def test_forward_anthropic_raises_not_implemented():
    """OllamaAdapter.forward_anthropic must raise NotImplementedError."""
    async def _run():
        adapter = OllamaAdapter()
        with pytest.raises(NotImplementedError):
            async for _ in adapter.forward_anthropic({}, stream=False):
                pass

    asyncio.run(_run())
