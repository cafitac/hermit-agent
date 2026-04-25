from __future__ import annotations

from typing import Any

from ..interactive_prompts import InteractivePrompt
from .protocols import InteractivePromptSink


class CompositeInteractivePromptSink:
    def __init__(self, *sinks: InteractivePromptSink) -> None:
        self._sinks = sinks

    def notify(self, prompt: InteractivePrompt) -> None:
        for sink in self._sinks:
            sink.notify(prompt)

    def clear(self, task_id: str, *, expected: Any | None = None) -> None:
        for sink in self._sinks:
            sink.clear(task_id, expected=expected)


def compose_interactive_prompt_sinks(
    *base_sinks: InteractivePromptSink,
    optional_sink: InteractivePromptSink | None = None,
) -> CompositeInteractivePromptSink:
    sinks = [*base_sinks]
    if optional_sink is not None:
        sinks.append(optional_sink)
    return CompositeInteractivePromptSink(*sinks)
