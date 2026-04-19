"""Z.ai provider adapter — supports both OpenAI and Anthropic wire formats."""
from __future__ import annotations

from typing import AsyncIterator

import httpx

from .base import ProviderAdapter


class ZaiAdapter(ProviderAdapter):
    """Forwards requests to z.ai using either OpenAI-compat or Anthropic wire format.

    Args:
        openai_base_url: Base URL for the OpenAI-compatible endpoint
            (e.g. ``https://api.z.ai/api/paas/v4``).
        anthropic_base_url: Base URL for the Anthropic-compatible endpoint
            (e.g. ``https://api.z.ai/api/anthropic``).
        api_key: API key used for both endpoints.
    """

    def __init__(
        self,
        openai_base_url: str,
        anthropic_base_url: str,
        api_key: str,
    ) -> None:
        self._openai_base_url = openai_base_url.rstrip("/")
        self._anthropic_base_url = anthropic_base_url.rstrip("/")
        self._api_key = api_key

    async def forward_openai(self, req_body: dict, stream: bool) -> AsyncIterator[bytes]:
        url = f"{self._openai_base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if stream:
            async with httpx.AsyncClient() as client:
                async with client.stream("POST", url, json=req_body, headers=headers) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
        else:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=req_body, headers=headers)
                yield resp.content

    async def forward_anthropic(self, req_body: dict, stream: bool) -> AsyncIterator[bytes]:
        url = f"{self._anthropic_base_url}/v1/messages"
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
        }
        if stream:
            async with httpx.AsyncClient() as client:
                async with client.stream("POST", url, json=req_body, headers=headers) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
        else:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=req_body, headers=headers)
                yield resp.content
