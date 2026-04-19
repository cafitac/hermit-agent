"""Provider adapters for the HermitAgent Gateway.

Each adapter forwards LLM requests to a specific upstream provider using
either OpenAI-compatible or Anthropic wire formats.
"""
from __future__ import annotations

from .base import ProviderAdapter
from .ollama import OllamaAdapter
from .zai import ZaiAdapter

__all__ = ["ProviderAdapter", "OllamaAdapter", "ZaiAdapter"]
