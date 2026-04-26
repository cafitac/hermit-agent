"""Concrete LLM provider implementations and factory.

Hierarchy:
  LLMClientBase (llm_client.py)
  ├── LocalLLMClient    — local backend (MLX, llama.cpp, Ollama)
  │   └── OllamaClient  — qwen3 reasoning_effort support
  └── OpenAICompatClient — standard OpenAI-compatible external API
      └── ZAIClient      — z.ai/GLM (glm-5.1/glm-4.7 routing)

Factory: create_llm_client(base_url, model, api_key) → auto-detect provider
"""
from __future__ import annotations

from .llm_client import LLMClientBase


class LocalLLMClient(LLMClientBase):
    """Local LLM client for any local backend (MLX, llama.cpp, Ollama).

    All local backends expose an OpenAI-compatible /v1 endpoint, so this
    single class handles them all via URL-based dispatch.
    """

    MODEL_ROUTING = {
        "quality": "qwen3-coder:30b",
        "speed": "qwen3-coder:30b",
        "fast": "qwen3-coder:30b",
    }

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        model: str = "qwen3-coder:30b",
        api_key: str | None = None,
    ):
        super().__init__(base_url, model, api_key)

    def _provider_extra_params(self, stream: bool) -> dict:
        return {}


class OllamaClient(LocalLLMClient):
    """Thin subclass adding qwen3 reasoning_effort support for Ollama.

    Use LocalLLMClient for non-ollama local backends (MLX, llama.cpp).
    """

    def _provider_extra_params(self, stream: bool) -> dict:
        """reasoning_effort: qwen3 thinking mode control parameter."""
        if not self.reasoning:
            return {"reasoning_effort": "none"}
        return {}


class OpenAICompatClient(LLMClientBase):
    """Standard OpenAI-compatible external API client.

    Used for z.ai/GLM, OpenAI, and other external services.
    Does not send non-standard parameters (e.g., reasoning_effort).
    """

    MODEL_ROUTING = {
        "quality": "gpt-4o",
        "speed": "gpt-4o-mini",
        "fast": "gpt-4o-mini",
    }

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
    ):
        super().__init__(base_url, model, api_key)

    def _provider_extra_params(self, stream: bool) -> dict:
        return {}


class ZAIClient(OpenAICompatClient):
    """z.ai/GLM API client.

    Environment variables:
      Z_AI_API_KEY   or   HERMIT_API_KEY
      HERMIT_MODEL  (default: glm-5.1)
"""

    DEFAULT_BASE_URL = "https://api.z.ai/api/coding/paas/v4"

    MODEL_ROUTING = {
        "quality": "glm-5.1",   # Code generation, review, complex reasoning
        "speed": "glm-4.7",     # Tasks requiring fast responses
        "fast": "glm-4.7",
    }

    def __init__(
        self,
        model: str = "glm-5.1",
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        import os
        resolved_key = api_key or os.environ.get("Z_AI_API_KEY") or os.environ.get("HERMIT_API_KEY")
        super().__init__(
            base_url=base_url or self.DEFAULT_BASE_URL,
            model=model,
            api_key=resolved_key,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


def create_llm_client(
    base_url: str = "http://localhost:11434/v1",
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
        # Ollama gets the subclass with reasoning_effort support
        if local_backend == "ollama":
            return OllamaClient(base_url=base_url, model=model or "qwen3-coder:30b", api_key=api_key)
        # MLX, llama.cpp, or unspecified → generic local client
        return LocalLLMClient(base_url=base_url, model=model or "qwen3-coder:30b", api_key=api_key)

    # Unknown external server → handled as standard OpenAI-compat
    return OpenAICompatClient(base_url=base_url, model=model or "gpt-4o", api_key=api_key)
