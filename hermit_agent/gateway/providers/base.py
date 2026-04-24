"""Abstract base class for LLM provider adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator


class ProviderAdapter(ABC):
    """Abstract adapter that forwards requests to an upstream LLM provider.

    Adapters that do not natively speak a format raise ``NotImplementedError``.
    Streaming yields SSE chunks as-received; non-streaming yields a single full body.
    """

    @abstractmethod
    def forward_openai(self, req_body: dict, stream: bool) -> AsyncIterator[bytes]:
        """Forward a request using the OpenAI chat/completions wire format."""
        ...

    @abstractmethod
    def forward_anthropic(self, req_body: dict, stream: bool) -> AsyncIterator[bytes]:
        """Forward a request using the Anthropic messages wire format."""
        ...
