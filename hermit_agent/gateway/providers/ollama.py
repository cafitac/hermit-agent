"""Ollama provider adapter — OpenAI-compatible wire format only."""
from __future__ import annotations

from typing import AsyncIterator

import httpx

from .base import ProviderAdapter


class OllamaAdapter(ProviderAdapter):
    """Forwards requests to a local Ollama instance via its OpenAI-compatible API.

    ``forward_anthropic`` raises ``NotImplementedError`` because Ollama does not
    natively speak the Anthropic messages wire format — use a translator layer.
    """

    def __init__(self, base_url: str = "http://localhost:11434/v1") -> None:
        self._base_url = base_url.rstrip("/")

    async def forward_openai(self, req_body: dict, stream: bool) -> AsyncIterator[bytes]:
        url = f"{self._base_url}/chat/completions"
        if stream:
            async with httpx.AsyncClient() as client:
                async with client.stream("POST", url, json=req_body) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
        else:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=req_body)
                yield resp.content

    async def forward_anthropic(self, req_body: dict, stream: bool) -> AsyncIterator[bytes]:
        raise NotImplementedError(
            "OllamaAdapter does not natively support Anthropic wire format — use the translator."
        )
        yield  # type: ignore[misc]  # unreachable; makes this an async generator
