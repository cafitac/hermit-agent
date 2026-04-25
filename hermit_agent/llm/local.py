from __future__ import annotations

from ..config import DEFAULTS as _CONFIG_DEFAULTS
from .base import LLMClientBase


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
        base_url: str = _CONFIG_DEFAULTS["ollama_url"],
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
