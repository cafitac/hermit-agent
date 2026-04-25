from __future__ import annotations

from typing import Any, Protocol

from ..interactive_prompts import InteractivePrompt


class InteractivePromptSink(Protocol):
    def notify(self, prompt: InteractivePrompt) -> None: ...

    def clear(self, task_id: str, *, expected: Any | None = None) -> None: ...


class CodexAppServerTransport(Protocol):
    def send_request(self, request: dict[str, Any]) -> object: ...
