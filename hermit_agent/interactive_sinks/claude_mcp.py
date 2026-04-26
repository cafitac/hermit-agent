from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..interactive_prompts import InteractivePrompt


class ClaudeMcpInteractiveSink:
    def __init__(self, *, notify: Callable[[str, dict[str, str]], None]) -> None:
        self._notify = notify

    def notify(self, prompt: InteractivePrompt) -> None:
        from ..interactive_prompts import channel_notification_meta

        self._notify(prompt.question, channel_notification_meta(prompt))

    def clear(self, task_id: str, *, expected: Any | None = None) -> None:
        return None
