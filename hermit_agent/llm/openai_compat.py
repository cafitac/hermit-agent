from __future__ import annotations

from .base import LLMClientBase


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
