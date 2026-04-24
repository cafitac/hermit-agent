"""Ollama provider adapter — OpenAI-compatible wire format only."""
from __future__ import annotations

from typing import AsyncIterator

import httpx

from .base import ProviderAdapter

# 2-hour read window — LLM streams can legitimately sit idle for tens
# of seconds between tokens (cold-start, queue wait). The httpx default
# 5s would kill every slow response; None would risk an infinite hang,
# so we cap at 7200s.
_CLIENT_TIMEOUT = httpx.Timeout(connect=10.0, read=7200.0, write=30.0, pool=5.0)


class OllamaAdapter(ProviderAdapter):
    """Forwards requests to a local Ollama instance via its OpenAI-compatible API.

    ``forward_anthropic`` raises ``NotImplementedError`` because Ollama does not
    natively speak the Anthropic messages wire format — use a translator layer.
    """

    def __init__(self, base_url: str = "http://localhost:11434/v1") -> None:
        self._base_url = base_url.rstrip("/")

    def forward_openai(self, req_body: dict, stream: bool) -> AsyncIterator[bytes]:
        url = f"{self._base_url}/chat/completions"
        async def _gen() -> AsyncIterator[bytes]:
            if stream:
                async with httpx.AsyncClient(timeout=_CLIENT_TIMEOUT) as client:
                    async with client.stream("POST", url, json=req_body) as resp:
                        async for chunk in resp.aiter_bytes():
                            yield chunk
            else:
                async with httpx.AsyncClient(timeout=_CLIENT_TIMEOUT) as client:
                    resp = await client.post(url, json=req_body)
                    yield resp.content

        return _gen()

    def forward_anthropic(self, req_body: dict, stream: bool) -> AsyncIterator[bytes]:
        async def _gen() -> AsyncIterator[bytes]:
            raise NotImplementedError(
                "OllamaAdapter does not natively support Anthropic wire format — use the translator."
            )
            yield b""

        return _gen()
