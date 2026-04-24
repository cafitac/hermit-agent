"""Z.ai provider adapter — supports both OpenAI and Anthropic wire formats."""
from __future__ import annotations

from typing import AsyncIterator

import httpx

from .base import ProviderAdapter

# 2-hour read window — LLM streams can legitimately sit idle for tens
# of seconds between tokens (cold-start, queue wait). The httpx default
# 5s would kill every slow response; None would risk an infinite hang,
# so we cap at 7200s.
_CLIENT_TIMEOUT = httpx.Timeout(connect=10.0, read=7200.0, write=30.0, pool=5.0)


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

    def forward_openai(self, req_body: dict, stream: bool) -> AsyncIterator[bytes]:
        url = f"{self._openai_base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async def _gen() -> AsyncIterator[bytes]:
            if stream:
                async with httpx.AsyncClient(timeout=_CLIENT_TIMEOUT) as client:
                    async with client.stream("POST", url, json=req_body, headers=headers) as resp:
                        async for chunk in resp.aiter_bytes():
                            yield chunk
            else:
                async with httpx.AsyncClient(timeout=_CLIENT_TIMEOUT) as client:
                    resp = await client.post(url, json=req_body, headers=headers)
                    yield resp.content

        return _gen()

    def forward_anthropic(self, req_body: dict, stream: bool) -> AsyncIterator[bytes]:
        url = f"{self._anthropic_base_url}/v1/messages"
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
        }
        async def _gen() -> AsyncIterator[bytes]:
            if stream:
                async with httpx.AsyncClient(timeout=_CLIENT_TIMEOUT) as client:
                    async with client.stream("POST", url, json=req_body, headers=headers) as resp:
                        async for chunk in resp.aiter_bytes():
                            yield chunk
            else:
                async with httpx.AsyncClient(timeout=_CLIENT_TIMEOUT) as client:
                    resp = await client.post(url, json=req_body, headers=headers)
                    yield resp.content

        return _gen()
