from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class TokenUsage:
    """Accumulated LLM token counts across one or more API calls."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0

    def accumulate(self, raw: dict) -> None:
        """Add token counts from a raw API usage dict (OpenAI format)."""
        self.prompt_tokens += raw.get("prompt_tokens", 0)
        self.completion_tokens += raw.get("completion_tokens", 0)
        self.cached_tokens += (raw.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        self.reasoning_tokens += (raw.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict | None = None  # {"prompt_tokens": N, "completion_tokens": N}

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class StreamChunk:
    """Streaming chunk."""
    type: Literal["text", "reasoning", "tool_call_start", "tool_call_done", "done", "usage"]
    text: str = ""
    tool_call: ToolCall | None = None
    usage: dict | None = None  # only populated in type="usage" chunks


class LLMCallTimeout(TimeoutError):
    """LLM call exceeds CALL_TIMEOUT or user cancels (§32 G30-C)."""
