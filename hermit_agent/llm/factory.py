from __future__ import annotations

from ..config import DEFAULTS as _CONFIG_DEFAULTS
from .base import LLMClientBase
from .local import LocalLLMClient, OllamaClient
from .openai_compat import OpenAICompatClient, ZAIClient

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


def create_llm_client(
    base_url: str = _CONFIG_DEFAULTS["ollama_url"],
    model: str | None = None,
    api_key: str | None = None,
    local_backend: str | None = None,
) -> LLMClientBase:
    """Auto-detects the provider from base_url and returns the appropriate client.

    For local hosts, uses OllamaClient (qwen3 reasoning_effort) only when
    local_backend is "ollama".  All other local backends get LocalLLMClient.
    """
    url = base_url.lower()

    if "z.ai" in url:
        return ZAIClient(base_url=base_url, model=model or "glm-5.1", api_key=api_key)

    if any(h in url for h in _LOCAL_HOSTS):
        if local_backend == "ollama":
            return OllamaClient(base_url=base_url, model=model or "qwen3-coder:30b", api_key=api_key)
        return LocalLLMClient(base_url=base_url, model=model or "qwen3-coder:30b", api_key=api_key)

    return OpenAICompatClient(base_url=base_url, model=model or "gpt-4o", api_key=api_key)
